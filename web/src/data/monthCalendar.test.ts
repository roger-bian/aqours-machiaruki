import { describe, expect, it } from 'vitest'
import {
  buildMonthGrid,
  monthOf,
  shiftMonth,
  showCalendarFor,
} from './monthCalendar'
import { openStatusFor } from './openStatus'
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
    hol_overrides_closed: false,
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

/** Openness of one day, by date string. */
function on(grid: ReturnType<typeof buildMonthGrid>, date: string) {
  const day = grid.days.find((d) => d.date === date)
  if (!day) throw new Error(`${date} not in grid`)
  return day.openness
}

// 2026-08-01 is a Saturday, so August 2026 needs 6 leading blanks and has 31
// days. 2026-08-11 is 山の日, a Tuesday. 2026-07-20 is 海の日 and the 3rd Monday.
// July 2026 puts the 2nd and 4th Tuesdays on the 14th and 28th.

describe('grid shape', () => {
  it('pads the first week and covers every day of the month', () => {
    const grid = buildMonthGrid(hours(), 2026, 8)
    expect(grid.leadingBlanks).toBe(6) // Aug 1 2026 is a Saturday, 日曜始まり
    expect(grid.days).toHaveLength(31)
    expect(grid.days[0].date).toBe('2026-08-01')
    expect(grid.days[30].date).toBe('2026-08-31')
  })

  it('handles a leap February', () => {
    expect(buildMonthGrid(hours(), 2028, 2).days).toHaveLength(29)
    expect(buildMonthGrid(hours(), 2026, 2).days).toHaveLength(28)
  })

  it('names the holidays in the month', () => {
    const grid = buildMonthGrid(hours(), 2026, 8)
    expect(on(grid, '2026-08-11')).toBe('open')
    expect(grid.days.find((d) => d.date === '2026-08-11')?.holiday).toBe('山の日')
    expect(grid.days.find((d) => d.date === '2026-08-10')?.holiday).toBeNull()
  })
})

describe('closures', () => {
  it('closes every occurrence of a weekly 定休日', () => {
    const grid = buildMonthGrid(hours({ closed: ['wed'] }), 2026, 8)
    // Wednesdays in Aug 2026: 5, 12, 19, 26
    for (const day of ['05', '12', '19', '26']) {
      expect(on(grid, `2026-08-${day}`), day).toBe('closed')
    }
    expect(on(grid, '2026-08-06')).toBe('open')
  })

  it('closes only the listed occurrences of an nth-week rule', () => {
    const grid = buildMonthGrid(
      hours({ closed_nth: [{ day: 'tue', nth: [2, 4] }] }), 2026, 7,
    )
    expect(on(grid, '2026-07-14')).toBe('closed') // 2nd Tuesday
    expect(on(grid, '2026-07-28')).toBe('closed') // 4th Tuesday
    expect(on(grid, '2026-07-07')).toBe('open') // 1st
    expect(on(grid, '2026-07-21')).toBe('open') // 3rd
  })

  it('applies closed_dates in every year, since they carry no year', () => {
    const shut = hours({ closed_dates: ['01-01'] })
    expect(on(buildMonthGrid(shut, 2026, 1), '2026-01-01')).toBe('closed')
    expect(on(buildMonthGrid(shut, 2027, 1), '2027-01-01')).toBe('closed')
    expect(on(buildMonthGrid(shut, 2026, 1), '2026-01-02')).toBe('open')
  })

  it('opens every day of an always_open location', () => {
    const grid = buildMonthGrid(hours({ always_open: true }), 2026, 8)
    expect(grid.days.every((d) => d.openness === 'open')).toBe(true)
  })
})

describe('holidays', () => {
  it('uses the hol schedule where the source stated one', () => {
    const grid = buildMonthGrid(hours({ closed: ['hol'] }), 2026, 7)
    expect(on(grid, '2026-07-20')).toBe('closed') // 海の日
    expect(on(grid, '2026-07-13')).toBe('open') // an ordinary Monday
    expect(on(grid, '2026-07-27')).toBe('open')
  })

  it('falls back to the weekday where it did not', () => {
    // 明治茶館: weekends only, 定休日 月～金, no 祝日 hours at all. 海の日 on a
    // Monday has to follow 月～金 rather than becoming 不明.
    const weekendsOnly = buildMonthGrid(hours({
      weekly: weekly({ sat: [[600, 960]], sun: [[600, 960]] }),
      closed: ['mon', 'tue', 'wed', 'thu', 'fri'],
    }), 2026, 7)
    expect(on(weekendsOnly, '2026-07-20')).toBe('closed')
    expect(on(weekendsOnly, '2026-07-18')).toBe('open') // Saturday
  })

  it('keeps a 定休日 shut on a day that is also a 祝日', () => {
    // 古安 (#120): blanket 8:30~18:30 fills 'hol' too, so 山の日 on a Tuesday
    // used to show 営業 in the grid against a 定休日 of 火曜日
    const closedTuesdays = buildMonthGrid(hours({
      weekly: weekly({
        mon: [[510, 1110]], wed: [[510, 1110]], thu: [[510, 1110]],
        fri: [[510, 1110]], sat: [[510, 1110]], sun: [[510, 1110]],
        hol: [[510, 1110]],
      }),
      closed: ['tue'],
    }), 2026, 8)
    // Tuesdays in Aug 2026: 4, 11 (山の日), 18, 25
    for (const day of ['04', '11', '18', '25']) {
      expect(on(closedTuesdays, `2026-08-${day}`), day).toBe('closed')
    }
    expect(closedTuesdays.unknownDays).toEqual([])
  })

  it('opens the 祝日 where the source lifts the closure', () => {
    // 沼津市歴史民俗資料館: 休館日 毎週月曜日（祝日は開館）
    const grid = buildMonthGrid(hours({
      weekly: { ...everyDay([540, 960]), mon: [] },
      closed: ['mon'],
      hol_overrides_closed: true,
    }), 2026, 7)
    expect(on(grid, '2026-07-20')).toBe('open') // 海の日, a Monday
    expect(on(grid, '2026-07-13')).toBe('closed') // an ordinary Monday
  })

  it('still matches an nth-week rule against the calendar weekday', () => {
    // 2026-07-20 is 海の日 *and* the 3rd Monday; 第3月曜日 applies either way
    const grid = buildMonthGrid(
      hours({ closed_nth: [{ day: 'mon', nth: [3] }] }), 2026, 7,
    )
    expect(on(grid, '2026-07-20')).toBe('closed')
  })
})

describe('days the source says nothing about', () => {
  // JEWELRY＆WATCH 市川 before the 平日 rule landed: 平日 and 日祝 stated, 土曜
  // never mentioned. No corpus row reaches this any more, which is exactly why
  // it needs a test - the state is now only reachable from new upstream data.
  const noSaturday = hours({
    weekly: weekly({
      mon: [[600, 1110]], tue: [[600, 1110]], thu: [[600, 1110]],
      fri: [[600, 1110]], sun: [[600, 1080]], hol: [[600, 1080]],
    }),
    closed: ['wed'],
  })

  it('reads 不明, not 休み', () => {
    const grid = buildMonthGrid(noSaturday, 2026, 8)
    // Saturdays in Aug 2026: 1, 8, 15, 22, 29
    for (const day of ['01', '08', '15', '22', '29']) {
      expect(on(grid, `2026-08-${day}`), day).toBe('unknown')
    }
    expect(on(grid, '2026-08-05')).toBe('closed') // stated 水曜日
    expect(on(grid, '2026-08-06')).toBe('open')
  })

  it('reports which weekdays were unstated, deduped', () => {
    expect(buildMonthGrid(noSaturday, 2026, 8).unknownDays).toEqual(['sat'])
    expect(buildMonthGrid(hours(), 2026, 8).unknownDays).toEqual([])
  })

  it('blames the weekday, not 祝日, for an unknown holiday', () => {
    // 2026-08-11 is 山の日 on a Tuesday. With no 祝日 hours the fallback lands on
    // tue, so tue is the gap to name - saying 祝日 would point at the wrong one.
    const noTuesday = hours({
      weekly: weekly({
        mon: [[600, 1200]], wed: [[600, 1200]], thu: [[600, 1200]],
        fri: [[600, 1200]], sat: [[600, 1200]], sun: [[600, 1200]],
      }),
    })
    const grid = buildMonthGrid(noTuesday, 2026, 8)
    expect(on(grid, '2026-08-11')).toBe('unknown')
    expect(grid.unknownDays).toEqual(['tue'])
  })

  it('counts an opening time with no stated close as open', () => {
    // 沼津ラクーンよしもと劇場: 土日祝 open 11:30, close 公演終了時間
    const openEnded = buildMonthGrid(hours({
      weekly: weekly({
        mon: [[900, 1080]], tue: [[900, 1080]], wed: [[900, 1080]],
        thu: [[900, 1080]], fri: [[900, 1080]],
        sat: [[690, null]], sun: [[690, null]], hol: [[690, null]],
      }),
    }), 2026, 8)
    expect(on(openEnded, '2026-08-01')).toBe('open') // Saturday
    expect(on(openEnded, '2026-08-11')).toBe('open') // 山の日
    expect(openEnded.unknownDays).toEqual([])
  })
})

describe('showCalendarFor', () => {
  it('hides a location with no schedule at all', () => {
    expect(showCalendarFor(null)).toBe(false)
    expect(showCalendarFor(hours({ weekly: null }))).toBe(false)
  })

  it('hides a permanently closed location', () => {
    // the struck-through grey title already carries that; a month of shut cells
    // adds nothing to it
    expect(showCalendarFor(hours({ permanently_closed: true }))).toBe(false)
  })

  it('shows an ordinary location', () => {
    expect(showCalendarFor(hours())).toBe(true)
    expect(showCalendarFor(hours({ irregular: true }))).toBe(true)
  })
})

describe('month arithmetic', () => {
  it('opens on the JST month, not the device one', () => {
    // 2026-07-31T16:00Z is already 2026-08-01 01:00 in Numazu
    expect(monthOf(new Date('2026-07-31T16:00:00Z'))).toEqual({ year: 2026, month: 8 })
    expect(monthOf(jst('2026-08-04T12:00'))).toEqual({ year: 2026, month: 8 })
  })

  it('rolls over both year boundaries', () => {
    expect(shiftMonth(2026, 12, 1)).toEqual({ year: 2027, month: 1 })
    expect(shiftMonth(2026, 1, -1)).toEqual({ year: 2025, month: 12 })
    expect(shiftMonth(2026, 8, 0)).toEqual({ year: 2026, month: 8 })
    expect(shiftMonth(2026, 3, -14)).toEqual({ year: 2025, month: 1 })
  })
})

// The grid and the marker ring answer the same question at different
// granularities, and they are built from the same isClosedOn/scheduleKey pair so
// that they cannot drift. This pins that: openStatusFor and dayOpennessFor must
// agree about every day of a month.
describe('agreement with openStatusFor', () => {
  const SAMPLES = Array.from({ length: 48 }, (_, i) => i * 30)

  function statusesAcross(h: HoursJson, date: string) {
    return SAMPLES.map((mins) => {
      const hh = String(Math.floor(mins / 60)).padStart(2, '0')
      const mm = String(mins % 60).padStart(2, '0')
      return openStatusFor(h, jst(`${date}T${hh}:${mm}`))
    })
  }

  // No overnight interval in any of these: a shift running past midnight makes
  // the two deliberately disagree, since openStatusFor looks back a day and the
  // calendar judges a date by its own hours. That exclusion is the point of
  // dayOpennessFor's contract, not a gap in it.
  const FIXTURES: [string, HoursJson][] = [
    ['plain weekly', hours()],
    ['weekly 定休日', hours({ closed: ['wed'] })],
    ['祝日 closed', hours({ closed: ['hol'] })],
    ['nth-week rule', hours({ closed_nth: [{ day: 'tue', nth: [2, 4] }] })],
    ['fixed dates', hours({ closed_dates: ['08-11', '08-15'] })],
    ['always open', hours({ always_open: true })],
    ['split shift', hours({ weekly: everyDay([690, 840], [1020, 1260]) })],
    ['unstated Saturday', hours({
      weekly: weekly({
        mon: [[600, 1110]], tue: [[600, 1110]], thu: [[600, 1110]],
        fri: [[600, 1110]], sun: [[600, 1080]], hol: [[600, 1080]],
      }),
      closed: ['wed'],
    })],
    ['unstated close', hours({ weekly: everyDay([690, null]) })],
    ['weekday fallback', hours({
      weekly: weekly({ sat: [[600, 960]], sun: [[600, 960]] }),
      closed: ['mon', 'tue', 'wed', 'thu', 'fri'],
    })],
    // 山の日 falls on a Tuesday in Aug 2026, so these two exercise both readings
    // of a closure that collides with a 祝日
    ['定休日 over a 祝日', hours({
      weekly: { ...everyDay([510, 1110]), tue: [] },
      closed: ['tue'],
    })],
    ['祝日 lifting a 定休日', hours({
      weekly: { ...everyDay([510, 1110]), tue: [] },
      closed: ['tue'],
      hol_overrides_closed: true,
    })],
  ]

  for (const [label, h] of FIXTURES) {
    it(`matches openStatusFor over a month: ${label}`, () => {
      for (const day of buildMonthGrid(h, 2026, 8).days) {
        const statuses = statusesAcross(h, day.date)
        const everOpen = statuses.some((s) => s === 'open' || s === 'closing_soon')
        const everUnknown = statuses.some((s) => s === 'hours_unknown')

        if (day.openness === 'open') {
          expect(everOpen, `${day.date} should be open at some point`).toBe(true)
        } else {
          expect(everOpen, `${day.date} should never read open`).toBe(false)
        }
        expect(everUnknown, `${day.date} unknown mismatch`)
          .toBe(day.openness === 'unknown')
      }
    })
  }
})
