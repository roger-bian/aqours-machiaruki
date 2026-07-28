import { describe, expect, it } from 'vitest'
import {
  closingTimeFor,
  dayKeyInJst,
  minutesInJst,
  openStatusFor,
} from './openStatus'
import type { DayKey, HoursJson, Interval } from './types'

const DAYS: DayKey[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'hol']

function weekly(perDay: Partial<Record<DayKey, Interval[]>>): Record<DayKey, Interval[]> {
  return Object.fromEntries(
    DAYS.map((day) => [day, perDay[day] ?? []]),
  ) as Record<DayKey, Interval[]>
}

function everyDay(...intervals: Interval[]): Record<DayKey, Interval[]> {
  return weekly(Object.fromEntries(DAYS.map((day) => [day, intervals])))
}

function hours(overrides: Partial<HoursJson> = {}): HoursJson {
  return {
    weekly: everyDay([600, 1200]), // 10:00-20:00 every day
    closed: [],
    closed_nth: [],
    closed_dates: [],
    always_open: false,
    irregular: false,
    permanently_closed: false,
    confidence: 'verified',
    notes: [],
    ...overrides,
  }
}

/** A wall-clock time in Numazu. JST is UTC+9 year-round, no DST. */
function jst(localIso: string): Date {
  return new Date(`${localIso}+09:00`)
}

// 2026-07-27 Mon, 07-28 Tue, 07-29 Wed, 08-01 Sat - none of them holidays.
// 2026-01-01 is 元日 and a Thursday; 2026-07-20 is 海の日 and a Monday.

describe('timezone handling', () => {
  it('resolves dates in Asia/Tokyo, not the device timezone', () => {
    // 16:00 UTC is already 01:00 the next day in Numazu
    const at = new Date('2026-07-27T16:00:00Z')
    expect(dayKeyInJst(at)).toBe('tue')
    expect(minutesInJst(at)).toBe(60)
  })

  it('treats a Japanese public holiday as its own schedule key', () => {
    // the source text categorises 祝日 separately (土日祝, 日曜日・祝日), so a
    // holiday is never just its weekday
    expect(dayKeyInJst(jst('2026-01-01T12:00'))).toBe('hol')
    expect(dayKeyInJst(jst('2026-07-28T12:00'))).toBe('tue')
  })
})

describe('interval boundaries', () => {
  it('is open at the opening minute', () => {
    expect(openStatusFor(hours(), jst('2026-07-28T10:00'))).toBe('open')
  })

  it('is still open the minute before closing', () => {
    expect(openStatusFor(hours(), jst('2026-07-28T19:59'))).toBe('closing_soon')
  })

  it('is closed at the closing minute, not open', () => {
    expect(openStatusFor(hours(), jst('2026-07-28T20:00'))).toBe('closed')
  })

  it('is closed before opening', () => {
    expect(openStatusFor(hours(), jst('2026-07-28T09:59'))).toBe('closed')
  })

  it('reads closing_soon exactly two hours out and open a minute earlier', () => {
    expect(openStatusFor(hours(), jst('2026-07-28T18:00'))).toBe('closing_soon')
    expect(openStatusFor(hours(), jst('2026-07-28T17:59'))).toBe('open')
  })

  it('handles a split shift', () => {
    const split = hours({ weekly: everyDay([690, 840], [1020, 1260]) })
    expect(openStatusFor(split, jst('2026-07-28T12:00'))).toBe('closing_soon')
    expect(openStatusFor(split, jst('2026-07-28T15:00'))).toBe('closed')
    expect(openStatusFor(split, jst('2026-07-28T18:00'))).toBe('open')
  })
})

describe('branch ordering', () => {
  // This ordering is the load-bearing part of openStatusFor and it is invisible
  // from the outside - each of these would silently paint the wrong marker ring.

  it('reports permanently_closed even inside the stated hours', () => {
    const shut = hours({ permanently_closed: true })
    expect(openStatusFor(shut, jst('2026-07-28T12:00'))).toBe('permanently_closed')
  })

  it('reports permanently_closed ahead of always_open', () => {
    const shut = hours({ permanently_closed: true, always_open: true })
    expect(openStatusFor(shut, jst('2026-07-28T12:00'))).toBe('permanently_closed')
  })

  it('reports permanently_closed even with no hours at all', () => {
    const shut = hours({ weekly: null, permanently_closed: true })
    expect(openStatusFor(shut, jst('2026-07-28T12:00'))).toBe('permanently_closed')
  })

  it('reports unknown when the source stated no hours', () => {
    expect(openStatusFor(hours({ weekly: null }), jst('2026-07-28T12:00'))).toBe('unknown')
  })

  it('reports unknown for a location with no hours_json row at all', () => {
    expect(openStatusFor(null, jst('2026-07-28T12:00'))).toBe('unknown')
  })

  it('prefers unknown over always_open when there are no hours', () => {
    // 'unknown' draws no ring; claiming a 24h schedule off an empty weekly would
    // be a confident wrong answer
    const odd = hours({ weekly: null, always_open: true })
    expect(openStatusFor(odd, jst('2026-07-28T12:00'))).toBe('unknown')
  })

  it('never reports closing_soon for a 24h location', () => {
    const always = hours({ weekly: everyDay([0, 1440]), always_open: true })
    expect(openStatusFor(always, jst('2026-07-28T23:30'))).toBe('open')
    expect(openStatusFor(always, jst('2026-07-28T04:00'))).toBe('open')
  })
})

describe('closures', () => {
  it('honours a specific closed date', () => {
    const closed = hours({ closed_dates: ['12-31'] })
    expect(openStatusFor(closed, jst('2026-12-31T12:00'))).toBe('closed')
    expect(openStatusFor(closed, jst('2026-12-30T12:00'))).toBe('open')
  })

  it('honours a closed weekday', () => {
    const closed = hours({ weekly: weekly({ tue: [[600, 1200]] }), closed: ['wed'] })
    expect(openStatusFor(closed, jst('2026-07-29T12:00'))).toBe('closed')
    expect(openStatusFor(closed, jst('2026-07-28T12:00'))).toBe('open')
  })

  it('honours a closed holiday', () => {
    const closed = hours({ closed: ['hol'] })
    // 元日, which is also a Thursday - the hol key wins
    expect(openStatusFor(closed, jst('2026-01-01T12:00'))).toBe('closed')
  })

  it('uses the holiday intervals rather than the weekday ones', () => {
    const shorter = hours({
      weekly: weekly({ thu: [[600, 1200]], hol: [[600, 720]] }),
    })
    // if this fell through to thu it would read 'open' (8h left), not closing_soon
    expect(openStatusFor(shorter, jst('2026-01-01T11:00'))).toBe('closing_soon')
  })

  it('closes only on the listed occurrences of an nth-week rule', () => {
    const nth = hours({ closed_nth: [{ day: 'tue', nth: [2, 4] }] })
    expect(openStatusFor(nth, jst('2026-07-14T12:00'))).toBe('closed') // 2nd Tuesday
    expect(openStatusFor(nth, jst('2026-07-21T12:00'))).toBe('open') // 3rd Tuesday
    expect(openStatusFor(nth, jst('2026-07-28T12:00'))).toBe('closed') // 4th Tuesday
  })

  it('matches an nth-week rule against the calendar weekday, not the schedule key', () => {
    // 2026-07-20 is the 3rd Monday and also 海の日, so scheduleKey is 'hol' while
    // 第3月曜日 still applies
    const nth = hours({ closed_nth: [{ day: 'mon', nth: [3] }] })
    expect(openStatusFor(nth, jst('2026-07-20T12:00'))).toBe('closed')
  })

  it('keeps the hours on an nth-closed day for the other weeks', () => {
    const nth = hours({ closed_nth: [{ day: 'tue', nth: [2] }] })
    expect(closingTimeFor(nth, jst('2026-07-21T12:00'))).toBe('20:00')
  })
})

describe('shifts running past midnight', () => {
  // 11:00~26:00 is stored as [660, 1560]; the shift belongs to the previous day,
  // so an early-morning "now" has to look back or every late-night bar reads shut

  it('is open in the early hours from the previous day’s shift', () => {
    const overnight = hours({ weekly: weekly({ mon: [[660, 1680]] }) })
    expect(openStatusFor(overnight, jst('2026-07-28T01:00'))).toBe('open')
  })

  it('reports closing_soon near the end of an overnight shift', () => {
    const overnight = hours({ weekly: weekly({ mon: [[660, 1560]] }) })
    expect(openStatusFor(overnight, jst('2026-07-28T01:00'))).toBe('closing_soon')
  })

  it('is closed once the overnight shift has ended', () => {
    const overnight = hours({ weekly: weekly({ mon: [[660, 1560]] }) })
    expect(openStatusFor(overnight, jst('2026-07-28T03:00'))).toBe('closed')
  })

  it('does not look back into a day the location was closed', () => {
    const overnight = hours({
      weekly: weekly({ mon: [[660, 1560]] }),
      closed_dates: ['07-27'],
    })
    expect(openStatusFor(overnight, jst('2026-07-28T01:00'))).toBe('closed')
  })

  it('only looks back at intervals that actually cross midnight', () => {
    const daytime = hours({ weekly: weekly({ mon: [[600, 1200]] }) })
    expect(openStatusFor(daytime, jst('2026-07-28T01:00'))).toBe('closed')
  })
})

describe('closingTimeFor', () => {
  it('returns the end of the current interval', () => {
    expect(closingTimeFor(hours(), jst('2026-07-28T17:00'))).toBe('20:00')
  })

  it('wraps a past-midnight end into a clock time', () => {
    const overnight = hours({ weekly: everyDay([660, 1560]) })
    expect(closingTimeFor(overnight, jst('2026-07-28T23:00'))).toBe('02:00')
  })

  it('zero-pads the hour and minute', () => {
    expect(closingTimeFor(hours({ weekly: everyDay([500, 545]) }),
      jst('2026-07-28T08:30'))).toBe('09:05')
  })

  it('returns null when there is no closing time to show', () => {
    const at = jst('2026-07-28T12:00')
    expect(closingTimeFor(null, at)).toBeNull()
    expect(closingTimeFor(hours({ weekly: null }), at)).toBeNull()
    expect(closingTimeFor(hours({ always_open: true }), at)).toBeNull()
    expect(closingTimeFor(hours({ permanently_closed: true }), at)).toBeNull()
    expect(closingTimeFor(hours({ closed: ['tue'] }), at)).toBeNull()
  })

  it('returns null outside opening hours', () => {
    expect(closingTimeFor(hours(), jst('2026-07-28T21:00'))).toBeNull()
  })
})
