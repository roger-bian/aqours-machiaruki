import * as holidayJp from '@holiday-jp/holiday_jp';
import type { DayKey, HoursJson, Interval, OpenStatus } from './types';

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
  minutes: number; // minutes since midnight
};

function jstParts(at: Date): JstParts {
  const p: Record<string, string> = {};
  for (const { type, value } of JST.formatToParts(at)) p[type] = value;
  return {
    date: `${p.year}-${p.month}-${p.day}`,
    monthDay: `${p.month}-${p.day}`,
    dayOfMonth: Number(p.day),
    weekday: WEEKDAYS[p.weekday],
    minutes: Number(p.hour) * 60 + Number(p.minute),
  };
}

/** The schedule key for a date: 'hol' on a Japanese public holiday (which the
 *  source text treats as its own category in `土日祝` / `日曜日・祝日`),
 *  otherwise the weekday. */
function scheduleKey(parts: JstParts): DayKey {
  return holidayJp.isHoliday(parts.date) ? 'hol' : parts.weekday;
}

/** Exposed for the detail panel, which shows today's hours. */
export function dayKeyInJst(at: Date): DayKey {
  return scheduleKey(jstParts(at));
}

// holiday_jp's own date-keyed map. Read directly rather than via `between()`,
// which formats its Date arguments in the device timezone - same reason
// isHoliday() is called with a YYYY-MM-DD string above.
const HOLIDAYS = holidayJp.holidays as Record<
  string, { name: string } | undefined
>;

/** Japanese name of the public holiday on `at` in JST (海の日), else null.
 *  Shown by the clock panel. */
export function holidayNameInJst(at: Date): string | null {
  return HOLIDAYS[jstParts(at).date]?.name ?? null;
}

export function minutesInJst(at: Date): number {
  return jstParts(at).minutes;
}

function isClosedOn(h: HoursJson, parts: JstParts, key: DayKey): boolean {
  if (h.closed_dates.includes(parts.monthDay)) return true;
  if (h.closed.includes(key)) return true;
  // 第二・第四火曜日 - the rule is about the calendar weekday, so it is matched
  // against parts.weekday rather than the (possibly 'hol') schedule key
  const nth = Math.floor((parts.dayOfMonth - 1) / 7) + 1;
  return h.closed_nth.some(
    (r) => r.day === parts.weekday && r.nth.includes(nth),
  );
}

/** End of whichever interval contains `mins`, or null if none does. Shared so
 *  that openStatusFor and closingTimeFor cannot disagree about what "currently
 *  open" means - they each had their own copy of this loop, and drifted. */
function endOfIntervalAt(intervals: Interval[], mins: number): number | null {
  for (const [start, end] of intervals) {
    if (mins >= start && mins < end) return end;
  }
  return null;
}

function statusWithin(intervals: Interval[], mins: number): OpenStatus | null {
  const end = endOfIntervalAt(intervals, mins);
  if (end === null) return null;
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
 *  the previous day and are still running now. */
function overnightIntervals(h: HoursJson, key: DayKey): Interval[] {
  return (h.weekly?.[key] ?? []).filter(([, end]) => end > 1440);
}

export function openStatusFor(h: HoursJson | null, now: Date): OpenStatus {
  // checked before the clock: a shut-down shop is never "open", whatever the hour
  if (h?.permanently_closed) return 'permanently_closed';
  if (!h || !h.weekly) return 'unknown';
  // a 24h location never approaches a closing time
  if (h.always_open) return 'open';

  const today = jstParts(now);
  const todayKey = scheduleKey(today);
  if (!isClosedOn(h, today, todayKey)) {
    const status = statusWithin(h.weekly[todayKey] ?? [], today.minutes);
    if (status) return status;
  }

  // A shift that runs past midnight (`11:00~26:00` is stored as [660, 1560])
  // belongs to the previous day, so early-morning "now" has to look back.
  const yesterday = jstParts(new Date(now.getTime() - 24 * 60 * 60 * 1000));
  const yesterdayKey = scheduleKey(yesterday);
  if (!isClosedOn(h, yesterday, yesterdayKey)) {
    const status = statusWithin(
      overnightIntervals(h, yesterdayKey), today.minutes + 1440,
    );
    if (status) return status;
  }

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
  const todayKey = scheduleKey(today);
  if (!isClosedOn(h, today, todayKey)) {
    const end = endOfIntervalAt(h.weekly[todayKey] ?? [], today.minutes);
    if (end !== null) return formatMinutes(end);
  }

  const yesterday = jstParts(new Date(now.getTime() - 24 * 60 * 60 * 1000));
  const yesterdayKey = scheduleKey(yesterday);
  if (!isClosedOn(h, yesterday, yesterdayKey)) {
    const end = endOfIntervalAt(
      overnightIntervals(h, yesterdayKey), today.minutes + 1440,
    );
    if (end !== null) return formatMinutes(end);
  }

  return null;
}
