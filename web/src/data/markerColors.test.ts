import { describe, expect, it } from 'vitest'
import {
  BOTH_COLLECTED_COLOR,
  DEFAULT_MARKER_COLOR,
  ONE_COLLECTED_COLOR,
  colorFor,
  matchesFilters,
  ringColorFor,
} from './markerColors'
import type { DayKey, FilterKey, HoursJson, Interval, OpenStatus } from './types'

const DAYS: DayKey[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'hol']

function hours(overrides: Partial<HoursJson> = {}): HoursJson {
  const open: Interval[] = [[600, 1200]] // 10:00-20:00
  return {
    weekly: Object.fromEntries(DAYS.map((d) => [d, open])) as Record<DayKey, Interval[]>,
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

const DURING_HOURS = new Date('2026-07-28T03:00:00Z') // 12:00 JST, a Tuesday
const AFTER_HOURS = new Date('2026-07-28T13:00:00Z') // 22:00 JST

function filters(...keys: FilterKey[]) {
  return new Set(keys)
}

describe('colorFor', () => {
  // fill is the collection channel only; open/closed rides an independent ring
  it('is grey with nothing collected', () => {
    expect(colorFor({ stamp: false, badge: false })).toBe(DEFAULT_MARKER_COLOR)
  })

  it('is orange with one of the two collected', () => {
    expect(colorFor({ stamp: true, badge: false })).toBe(ONE_COLLECTED_COLOR)
    expect(colorFor({ stamp: false, badge: true })).toBe(ONE_COLLECTED_COLOR)
  })

  it('is blue with both collected', () => {
    expect(colorFor({ stamp: true, badge: true })).toBe(BOTH_COLLECTED_COLOR)
  })
})

describe('ringColorFor', () => {
  it('gives every known status a colour', () => {
    const statuses: OpenStatus[] = ['open', 'closing_soon', 'closed', 'permanently_closed']
    for (const status of statuses) {
      expect(ringColorFor(status)).toMatch(/^#[0-9a-f]{6}$/)
    }
  })

  it('draws no ring for either kind of unknown', () => {
    // a confident colour for a location whose hours aren't derivable would be
    // worse than showing nothing - 不定休 is not something a parser can resolve.
    // hours_unknown is the same call at day granularity: a ring answers "can I
    // go right now", and there the honest answer is nothing. The detail panel's
    // badge has room for words and distinguishes the two.
    expect(ringColorFor('unknown')).toBeNull()
    expect(ringColorFor('hours_unknown')).toBeNull()
  })

  it('distinguishes all four ring colours', () => {
    const drawn = ['open', 'closing_soon', 'closed', 'permanently_closed']
      .map((s) => ringColorFor(s as OpenStatus))
    expect(new Set(drawn).size).toBe(4)
  })
})

describe('matchesFilters', () => {
  const collected = { stamp: true, badge: true, hours_json: hours() }
  const partial = { stamp: true, badge: false, hours_json: hours() }

  it('keeps everything when nothing is ticked', () => {
    expect(matchesFilters(collected, filters(), DURING_HOURS)).toBe(true)
    expect(matchesFilters(partial, filters(), AFTER_HOURS)).toBe(true)
    expect(matchesFilters({ stamp: false, badge: false, hours_json: null },
      filters(), AFTER_HOURS)).toBe(true)
  })

  it('未獲得 excludes only fully collected locations', () => {
    expect(matchesFilters(collected, filters('uncollected'), DURING_HOURS)).toBe(false)
    expect(matchesFilters(partial, filters('uncollected'), DURING_HOURS)).toBe(true)
    expect(matchesFilters({ stamp: false, badge: false, hours_json: hours() },
      filters('uncollected'), DURING_HOURS)).toBe(true)
  })

  it('営業中のみ counts closing_soon as still open', () => {
    const closingSoon = { stamp: false, badge: false, hours_json: hours() }
    const at1830 = new Date('2026-07-28T09:30:00Z') // 18:30 JST, 90 min to close
    expect(matchesFilters(closingSoon, filters('open_now'), at1830)).toBe(true)
  })

  it('営業中のみ excludes closed, permanently closed and unknown', () => {
    expect(matchesFilters({ stamp: false, badge: false, hours_json: hours() },
      filters('open_now'), AFTER_HOURS)).toBe(false)
    expect(matchesFilters(
      { stamp: false, badge: false, hours_json: hours({ permanently_closed: true }) },
      filters('open_now'), DURING_HOURS)).toBe(false)
    expect(matchesFilters({ stamp: false, badge: false, hours_json: null },
      filters('open_now'), DURING_HOURS)).toBe(false)
    // a day the source never described is not a day the filter can promise is
    // open, so hours_unknown has to fail it the same way
    const noSaturday = hours({
      weekly: {
        mon: [[600, 1200]], tue: [[600, 1200]], wed: [[600, 1200]],
        thu: [[600, 1200]], fri: [[600, 1200]], sat: [], sun: [[600, 1200]],
        hol: [[600, 1200]],
      },
    })
    // 2026-08-01 is a Saturday
    expect(matchesFilters({ stamp: false, badge: false, hours_json: noSaturday },
      filters('open_now'), new Date('2026-08-01T03:00:00Z'))).toBe(false)
  })

  it('stacks the two filters with AND', () => {
    // one checkbox per concept, ANDed - this was an OR over per-field filters
    // before the panel was rebuilt, so it is exactly the kind of thing that
    // regresses back
    const both = filters('uncollected', 'open_now')
    expect(matchesFilters(partial, both, DURING_HOURS)).toBe(true)
    // uncollected but shut
    expect(matchesFilters(partial, both, AFTER_HOURS)).toBe(false)
    // open but fully collected
    expect(matchesFilters(collected, both, DURING_HOURS)).toBe(false)
  })
})
