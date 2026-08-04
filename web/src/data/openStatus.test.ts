import { describe, expect, it } from 'vitest'
import {
  closingTimeFor,
  dayKeyInJst,
  holidayNameInJst,
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

  it('names the holiday in Japanese, or null on an ordinary day', () => {
    expect(holidayNameInJst(jst('2026-07-20T12:00'))).toBe('海の日')
    expect(holidayNameInJst(jst('2026-01-01T12:00'))).toBe('元日')
    expect(holidayNameInJst(jst('2026-07-28T12:00'))).toBeNull()
  })

  it('picks the holiday by the JST date, not the device one', () => {
    // 2026-07-19T16:00Z is already 海の日 in Numazu; 07-20T16:00Z no longer is
    expect(holidayNameInJst(new Date('2026-07-19T16:00:00Z'))).toBe('海の日')
    expect(holidayNameInJst(new Date('2026-07-20T16:00:00Z'))).toBeNull()
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

// 祝日 is its own schedule category only where the source stated one. Where it
// did not, treating the day as 'hol' voids whatever the weekday said: 明治茶館 is
// 定休日 月～金 with no 祝日 hours, and 海の日 on a Monday used to escape that
// closure and land on an empty 'hol' instead of being plainly shut.
describe('a holiday the source never mentioned', () => {
  it('falls back to the weekday closure', () => {
    const weekdaysShut = hours({
      weekly: weekly({ sat: [[600, 960]], sun: [[600, 960]] }),
      closed: ['mon', 'tue', 'wed', 'thu', 'fri'],
    })
    // 2026-07-20 is 海の日 and a Monday
    expect(openStatusFor(weekdaysShut, jst('2026-07-20T12:00'))).toBe('closed')
  })

  it('falls back to the weekday hours', () => {
    const noHolidayHours = hours({ weekly: weekly({ mon: [[600, 1200]] }) })
    expect(openStatusFor(noHolidayHours, jst('2026-07-20T12:00'))).toBe('open')
    expect(closingTimeFor(noHolidayHours, jst('2026-07-20T12:00'))).toBe('20:00')
  })

  it('still prefers hol once the source states it, as hours or as a closure', () => {
    const statedHours = hours({
      weekly: weekly({ mon: [[600, 1200]], hol: [[600, 720]] }),
    })
    // 11:00 on 海の日: the hol interval ends at 12:00, the mon one at 20:00
    expect(openStatusFor(statedHours, jst('2026-07-20T11:00'))).toBe('closing_soon')

    const statedClosed = hours({
      weekly: weekly({ mon: [[600, 1200]] }),
      closed: ['hol'],
    })
    expect(openStatusFor(statedClosed, jst('2026-07-20T12:00'))).toBe('closed')
  })
})

describe('a day the source says nothing about', () => {
  // a shop listing 平日 and 日祝 hours has stated nothing at all about its
  // Saturday. Reporting 営業時間外 there asserts a closure nobody wrote.
  const noSaturday = hours({
    weekly: weekly({
      mon: [[600, 1110]], tue: [[600, 1110]], thu: [[600, 1110]],
      fri: [[600, 1110]], sun: [[600, 1080]], hol: [[600, 1080]],
    }),
    closed: ['wed'],
  })

  it('reports hours_unknown rather than closed', () => {
    // 2026-08-01 is a Saturday
    expect(openStatusFor(noSaturday, jst('2026-08-01T12:00'))).toBe('hours_unknown')
  })

  it('still reports a stated closure as closed', () => {
    expect(openStatusFor(noSaturday, jst('2026-07-29T12:00'))).toBe('closed')
  })

  it('has no closing time to report', () => {
    expect(closingTimeFor(noSaturday, jst('2026-08-01T12:00'))).toBeNull()
  })

  it('loses to an overnight shift still running from yesterday', () => {
    // checked after the look-back: 'hours_unknown' must not pre-empt a bar that
    // is genuinely still open at 01:00 on a day of its own it never described
    const overnightIntoGap = hours({
      weekly: weekly({ fri: [[1080, 1680]] }),
    })
    // 2026-08-01 is a Saturday; Friday's shift runs to 04:00, far enough out
    // that this is plainly 'open' rather than 'closing_soon'
    expect(openStatusFor(overnightIntoGap, jst('2026-08-01T01:00'))).toBe('open')
    expect(openStatusFor(overnightIntoGap, jst('2026-08-01T12:00'))).toBe('hours_unknown')
  })
})

describe('an opening time with no stated close', () => {
  // 沼津ラクーンよしもと劇場: 土日祝 open 11:30 and close at 公演終了時間
  const openEnded = hours({
    weekly: weekly({ mon: [[900, 1080]], sat: [[690, null]] }),
  })

  it('is open from its start with no closing time claimed', () => {
    expect(openStatusFor(openEnded, jst('2026-08-01T12:00'))).toBe('open')
    expect(closingTimeFor(openEnded, jst('2026-08-01T12:00'))).toBeNull()
  })

  it('never reads closing_soon, at any hour', () => {
    // there is no stated close, so nothing can be approaching one
    for (const at of ['12:00', '20:00', '23:00', '23:59']) {
      const status = openStatusFor(openEnded, jst(`2026-08-01T${at}`))
      expect(status, at).toBe('open')
    }
  })

  it('is not open before its start', () => {
    expect(openStatusFor(openEnded, jst('2026-08-01T11:00'))).toBe('closed')
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

  // these three state 定休日 for the Tuesday under test so the expected value
  // stays a plain 'closed'. Without it Tuesday has no hours *and* no stated
  // closure, which is 'hours_unknown' - a true answer, but about the source
  // being silent rather than about the look-back these tests exist to pin.
  it('is closed once the overnight shift has ended', () => {
    const overnight = hours({
      weekly: weekly({ mon: [[660, 1560]] }),
      closed: ['tue'],
    })
    expect(openStatusFor(overnight, jst('2026-07-28T03:00'))).toBe('closed')
  })

  it('does not look back into a day the location was closed', () => {
    const overnight = hours({
      weekly: weekly({ mon: [[660, 1560]] }),
      closed: ['tue'],
      closed_dates: ['07-27'],
    })
    expect(openStatusFor(overnight, jst('2026-07-28T01:00'))).toBe('closed')
  })

  it('only looks back at intervals that actually cross midnight', () => {
    const daytime = hours({
      weekly: weekly({ mon: [[600, 1200]] }),
      closed: ['tue'],
    })
    expect(openStatusFor(daytime, jst('2026-07-28T01:00'))).toBe('closed')
  })

  it('does not treat an unstated close as running past midnight', () => {
    // a null end says the close is unknown, which is not evidence it is after
    // midnight - reading it as overnight would have the theater open at 03:00
    const openEnded = hours({
      weekly: weekly({ mon: [[690, null]] }),
      closed: ['tue'],
    })
    expect(openStatusFor(openEnded, jst('2026-07-28T03:00'))).toBe('closed')
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

  it('looks back at a shift that started yesterday', () => {
    // openStatusFor says closing_soon here, so the badge renders まもなく閉店;
    // without the same look-back this returned null and the badge showed no time
    const overnight = hours({ weekly: weekly({ mon: [[660, 1560]] }) })
    const at0100 = jst('2026-07-28T01:00')
    expect(openStatusFor(overnight, at0100)).toBe('closing_soon')
    expect(closingTimeFor(overnight, at0100)).toBe('02:00')
  })

  it('does not look back into a day the location was closed', () => {
    const overnight = hours({
      weekly: weekly({ mon: [[660, 1560]] }),
      closed_dates: ['07-27'],
    })
    expect(closingTimeFor(overnight, jst('2026-07-28T01:00'))).toBeNull()
  })

  it('agrees with openStatusFor about whether it is open at all', () => {
    // the two used to keep their own copy of the interval loop and drifted; any
    // status other than closed/permanently_closed/unknown must have a time
    const cases: HoursJson[] = [
      hours(),
      hours({ weekly: everyDay([660, 1560]) }),
      hours({ weekly: weekly({ mon: [[660, 1560]] }) }),
      hours({ weekly: everyDay([690, 840], [1020, 1260]) }),
    ]
    const times = ['00:30', '01:00', '09:00', '12:00', '15:00', '19:30', '23:30']
    for (const h of cases) {
      for (const time of times) {
        const at = jst(`2026-07-28T${time}`)
        const status = openStatusFor(h, at)
        const closing = closingTimeFor(h, at)
        if (status === 'open' || status === 'closing_soon') {
          expect(closing, `${time} ${status}`).not.toBeNull()
        } else {
          expect(closing, `${time} ${status}`).toBeNull()
        }
      }
    }
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
