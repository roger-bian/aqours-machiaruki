import * as holidayJp from '@holiday-jp/holiday_jp';
import type {
  DayKey, DayOpenness, HoursJson, Interval, OpenStatus,
} from './types';

/** How long before closing a location reads as "closing soon". */
export const CLOSING_SOON_MINUTES = 120;

const WEEKDAYS: Record<string, DayKey> = {
  Mon: 'mon', Tue: 'tue', Wed: 'wed', Thu: 'thu',
  Fri: 'fri', Sat: 'sat', Sun: 'sun',
};

// Everything is evaluated in Asia/Tokyo, never the device timezone - the shops
// are in Numazu regardless of where the phone thinks it is.
const JST = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Tokyo',
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  weekday: 'short',
});

type JstParts = {
  date: string;    // YYYY-MM-DD
  monthDay: string; // MM-DD
  dayOfMonth: number;
  weekday: DayKey; // the calendar weekday, ignoring holidays
  isHoliday: boolean;
  minutes: number; // minutes since midnight
};

function jstParts(at: Date): JstParts {
  const p: Record<string, string> = {};
  for (const { type, value } of JST.formatToParts(at)) p[type] = value;
  const date = `${p.year}-${p.month}-${p.day}`;
  return {
    date,
    monthDay: `${p.month}-${p.day}`,
    dayOfMonth: Number(p.day),
    weekday: WEEKDAYS[p.weekday],
    isHoliday: holidayJp.isHoliday(date),
    minutes: Number(p.hour) * 60 + Number(p.minute),
  };
}

/** Whether the source actually stated a 祝日 schedule, either as hours or as a
 *  closure. When it did not, `hol` is an absence of information rather than a
 *  category, and the weekday is better evidence than nothing. */
function statesHolidays(h: HoursJson): boolean {
  return (h.weekly?.hol ?? []).length > 0 || h.closed.includes('hol');
}

/** Which day's *hours* apply to a date: 'hol' on a Japanese public holiday
 *  (which the source text treats as its own category in `土日祝` /
 *  `日曜日・祝日`), otherwise the weekday. Closures are read separately, off the
 *  calendar - see isClosedOn.
 *
 *  Falls back to the weekday on a holiday the source never mentioned. 明治茶館
 *  states 土曜・日曜 hours and no 祝日 ones: read as 'hol' a Saturday holiday
 *  landed on an empty schedule and became 営業時間不明, when the source plainly
 *  gave that day hours. Only 2 entries take this path - the other 122 either
 *  state 祝日 hours or state 祝日 closed. */
function scheduleKey(h: HoursJson, parts: JstParts): DayKey {
  if (!parts.isHoliday) return parts.weekday;
  return statesHolidays(h) ? 'hol' : parts.weekday;
}

/** The raw calendar key for a date, 'hol' on any public holiday regardless of
 *  what the source stated. Unlike `scheduleKey` this needs no `HoursJson`, and
 *  the two deliberately disagree on a holiday whose schedule was never given. */
export function dayKeyInJst(at: Date): DayKey {
  const parts = jstParts(at);
  return parts.isHoliday ? 'hol' : parts.weekday;
}

// holiday_jp's own date-keyed map. Read directly rather than via `between()`,
// which formats its Date arguments in the device timezone - same reason
// isHoliday() is called with a YYYY-MM-DD string above.
const HOLIDAYS = holidayJp.holidays as Record<
  string, { name: string } | undefined
>;

/** Japanese name of the public holiday on `date` (`YYYY-MM-DD`), else null.
 *  Marks 祝日 cells in the monthly calendar, whose schedule can differ from the
 *  weekday around it. */
export function holidayNameOn(date: string): string | null {
  return HOLIDAYS[date]?.name ?? null;
}

/** Japanese name of the public holiday on `at` in JST (海の日), else null.
 *  Shown by the clock panel. */
export function holidayNameInJst(at: Date): string | null {
  return holidayNameOn(jstParts(at).date);
}

/** Today's date in JST as `YYYY-MM-DD`. The calendar opens on this month and
 *  highlights this day; never derive either from the device clock. */
export function jstDateFor(at: Date): string {
  return jstParts(at).date;
}

export function minutesInJst(at: Date): number {
  return jstParts(at).minutes;
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** Index into this array is `Date.getUTCDay()`, and 日曜始まり is also the order
 *  the calendar's weekday headers use. */
const WEEKDAY_KEYS: DayKey[] = [
  'sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat',
];

function isoDate(at: Date): string {
  return `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`;
}

/** `YYYY-MM-DD` moved by whole days. All arithmetic goes through `Date.UTC`, so
 *  the device timezone cannot shift which day is which - a plain `new Date(s)`
 *  would. */
export function shiftDate(date: string, days: number): string {
  const [year, month, day] = date.split('-').map(Number);
  return isoDate(new Date(Date.UTC(year, month - 1, day + days)));
}

/** Calendar weekday of a `YYYY-MM-DD` string, never `'hol'`. */
export function weekdayKeyOn(date: string): DayKey {
  const [year, month, day] = date.split('-').map(Number);
  return WEEKDAY_KEYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
}

const WEEKEND: DayKey[] = ['sat', 'sun'];

/** The unbroken run of public holidays immediately before `date`, most recent
 *  first; empty on an ordinary day. What carries a deferred closure past a whole
 *  holiday run rather than one day. Bounded because it is a loop over library
 *  data: the longest real run is Golden Week's four (2026-05-03～06). */
function holidaysBefore(date: string): string[] {
  const run: string[] = [];
  for (let back = 1; back <= 7; back += 1) {
    const day = shiftDate(date, -back);
    if (!holidayJp.isHoliday(day)) break;
    run.push(day);
  }
  return run;
}

/** Whether `date` is the last Mon-Fri of its own month (`毎月最終の平日`). */
function isLastWeekdayOfMonth(date: string): boolean {
  const [year, month] = date.split('-').map(Number);
  // day 0 of the next month is the last day of this one, the same idiom
  // buildMonthGrid uses for its day count
  let candidate = isoDate(new Date(Date.UTC(year, month, 0)));
  while (WEEKEND.includes(weekdayKeyOn(candidate))) {
    candidate = shiftDate(candidate, -1);
  }
  return candidate === date;
}

/** Whether a date is a stated closure. Read off the **calendar weekday**, never
 *  the schedule key: `定休日 火曜日` shuts every Tuesday, including one that
 *  happens to be 海の日. Keying this on 'hol' let a holiday void the closure
 *  whenever the location also had 祝日 hours - which blanket hours like 古安's
 *  `8:30~18:30` fill in for every day, so 火曜日 + a holiday read 営業 against the
 *  very text stating the closure. Only what the source actually wrote lifts a
 *  weekday closure (`月曜日（祝日は開館）`), and that arrives as
 *  `hol_overrides_closed` - along with the three flags below saying where the
 *  closure goes instead. */
function isClosedOn(h: HoursJson, parts: JstParts): boolean {
  // a stated date wins outright, flag or not: 年末年始 spans 元日, and 休館 on
  // 元日 is precisely what those two museums wrote down
  if (h.closed_dates.includes(parts.monthDay)) return true;
  if (parts.isHoliday) {
    if (h.closed.includes('hol')) return true;
    if (h.hol_overrides_closed) return false;
  }
  if (h.closed.includes(parts.weekday)) return true;
  // 第二・第四火曜日 - a weekday closure like any other, counted on the calendar
  const nth = Math.floor((parts.dayOfMonth - 1) / 7) + 1;
  if (h.closed_nth.some((r) => r.day === parts.weekday && r.nth.includes(nth))) {
    return true;
  }
  // 毎月最終の平日 - 歴史民俗資料館's monthly maintenance day. Not a closed_nth
  // rule: it is whichever weekday happens to fall last, not a fixed one.
  if (h.closed_last_weekday && isLastWeekdayOfMonth(parts.date)) return true;

  // Closures displaced by a 祝日. Only reachable on a day that is not itself a
  // holiday - a holiday has already returned closed ('hol') or open
  // (hol_overrides_closed, which every flag below implies).
  if (!parts.isHoliday && (h.closed_after_hol || h.hol_defers_closed)) {
    const run = holidaysBefore(parts.date);
    if (run.length > 0) {
      // 祝日の翌日（土曜日・日曜日を除く）休館 - fires after *any* holiday, not
      // only one that landed on the weekly closure
      if (h.closed_after_hol && !WEEKEND.includes(parts.weekday)) return true;
      // 月曜日（祝日の場合は翌日）- the weekly closure moved here. Reading the
      // whole run is what carries it past Golden Week: 2026-05-04 is a closed
      // Monday and a holiday, 05-05 and 05-06 are holidays too, so the closure
      // lands on Thursday the 7th - the very day 芹沢's
      // 休日の翌日（土曜日・日曜日・休日を除く）reaches by its own sentence.
      if (h.hol_defers_closed
          && run.some((day) => h.closed.includes(weekdayKeyOn(day)))) {
        return true;
      }
    }
  }
  return false;
}

/** End of whichever interval contains `mins`: the minute it closes, `'open_ended'`
 *  when the source stated no close, or null when no interval contains it.
 *
 *  Shared so that openStatusFor and closingTimeFor cannot disagree about what
 *  "currently open" means - they each had their own copy of this loop, and
 *  drifted. The three-way result keeps that single copy now that an end can be
 *  null; two loops would reintroduce exactly the bug this function prevents. */
function endOfIntervalAt(
  intervals: Interval[], mins: number,
): number | 'open_ended' | null {
  for (const [start, end] of intervals) {
    if (mins < start) continue;
    if (end === null) return 'open_ended';
    if (mins < end) return end;
  }
  return null;
}

function statusWithin(intervals: Interval[], mins: number): OpenStatus | null {
  const end = endOfIntervalAt(intervals, mins);
  if (end === null) return null;
  // no stated close, so no way to know a close is approaching
  if (end === 'open_ended') return 'open';
  return end - mins <= CLOSING_SOON_MINUTES ? 'closing_soon' : 'open';
}

/** Minutes-from-midnight to `HH:MM`, wrapping a past-midnight end (1560 is
 *  02:00, not 26:00). */
function formatMinutes(total: number): string {
  const mins = total % 1440;
  const hh = String(Math.floor(mins / 60)).padStart(2, '0');
  return `${hh}:${String(mins % 60).padStart(2, '0')}`;
}

/** Intervals from `key` that run past midnight, i.e. the ones that belong to
 *  the previous day and are still running now. A null end is excluded - it says
 *  the close is unstated, which is not evidence that it is after midnight. */
function overnightIntervals(h: HoursJson, key: DayKey): Interval[] {
  return (h.weekly?.[key] ?? []).filter(([, end]) => end !== null && end > 1440);
}

export function openStatusFor(h: HoursJson | null, now: Date): OpenStatus {
  // checked before the clock: a shut-down shop is never "open", whatever the hour
  if (h?.permanently_closed) return 'permanently_closed';
  if (!h || !h.weekly) return 'unknown';
  // a 24h location never approaches a closing time
  if (h.always_open) return 'open';

  const today = jstParts(now);
  const todayKey = scheduleKey(h, today);
  const openToday = !isClosedOn(h, today);
  if (openToday) {
    const status = statusWithin(h.weekly[todayKey] ?? [], today.minutes);
    if (status) return status;
  }

  // A shift that runs past midnight (`11:00~26:00` is stored as [660, 1560])
  // belongs to the previous day, so early-morning "now" has to look back.
  const yesterday = jstParts(new Date(now.getTime() - 24 * 60 * 60 * 1000));
  const yesterdayKey = scheduleKey(h, yesterday);
  if (!isClosedOn(h, yesterday)) {
    const status = statusWithin(
      overnightIntervals(h, yesterdayKey), today.minutes + 1440,
    );
    if (status) return status;
  }

  // Hours are stated for other days but not this one, and no closure covers it
  // either. `closed` would assert a shutdown the source never wrote - a shop
  // listing 平日 and 日祝 hours says nothing at all about its Saturday. Checked
  // after the look-back so an overnight shift still reports open.
  if (openToday && (h.weekly[todayKey] ?? []).length === 0) return 'hours_unknown';

  return 'closed';
}

/** Next closing time as `HH:MM` in JST, or null when not currently open.
 *  Used by the detail panel badge ("まもなく閉店 (14:00)").
 *
 *  Mirrors openStatusFor's day resolution, including the look-back for a shift
 *  that started yesterday - without it, a bar open until 02:00 shows
 *  "まもなく閉店" with no time next to it at 01:00. */
export function closingTimeFor(h: HoursJson | null, now: Date): string | null {
  if (!h || !h.weekly || h.always_open || h.permanently_closed) return null;

  const today = jstParts(now);
  const todayKey = scheduleKey(h, today);
  if (!isClosedOn(h, today)) {
    // only a real minute formats; 'open_ended' falls through to null, which
    // already means "cannot say" to every caller
    const end = endOfIntervalAt(h.weekly[todayKey] ?? [], today.minutes);
    if (typeof end === 'number') return formatMinutes(end);
  }

  const yesterday = jstParts(new Date(now.getTime() - 24 * 60 * 60 * 1000));
  const yesterdayKey = scheduleKey(h, yesterday);
  if (!isClosedOn(h, yesterday)) {
    const end = endOfIntervalAt(
      overnightIntervals(h, yesterdayKey), today.minutes + 1440,
    );
    if (typeof end === 'number') return formatMinutes(end);
  }

  return null;
}

/** Whether a location is open at some point on the JST calendar date `date`
 *  (`YYYY-MM-DD`) - the only question the monthly calendar asks.
 *
 *  Built from the same isClosedOn/scheduleKey pair as openStatusFor, so the grid
 *  and the marker ring cannot disagree about whether a day is a closure.
 *
 *  An interval from the *previous* day running past midnight does not make this
 *  day open: "still serving at 01:00 because last night's shift has not ended"
 *  is not a day you can plan a visit around, and openStatusFor's look-back
 *  already covers the clock question. One corpus entry is overnight. */
export function dayOpennessFor(h: HoursJson, date: string): DayOpenness {
  if (h.permanently_closed) return 'closed';
  if (!h.weekly) return 'unknown';
  if (h.always_open) return 'open';

  const parts = jstParts(new Date(`${date}T00:00:00+09:00`));
  const key = scheduleKey(h, parts);
  if (isClosedOn(h, parts)) return 'closed';
  // no hours and no stated closure - the source is silent, not negative
  return (h.weekly[key] ?? []).length > 0 ? 'open' : 'unknown';
}
