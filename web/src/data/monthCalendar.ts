import {
  WEEKDAY_KEYS, dayOpennessFor, holidayNameOn, jstDateFor, pad, weekdayKeyOn,
} from './openStatus';
import type { DayKey, DayOpenness, HoursJson } from './types';

/** Weekday headers, 日曜始まり - the standard Japanese wall-calendar layout. Also
 *  the index order `leadingBlanks` and `Date.getUTCDay()` both use. */
export const WEEKDAY_HEADERS = ['日', '月', '火', '水', '木', '金', '土'];

const DAY_NAMES: Record<DayKey, string> = {
  mon: '月曜日', tue: '火曜日', wed: '水曜日', thu: '木曜日',
  fri: '金曜日', sat: '土曜日', sun: '日曜日', hol: '祝日',
};

export type CalendarDay = {
  /** `YYYY-MM-DD` */
  date: string;
  dayOfMonth: number;
  openness: DayOpenness;
  /** 祝日 name, e.g. 海の日. Worth marking: a holiday's schedule can differ from
   *  the weekday around it, so an otherwise inexplicable cell is explained. */
  holiday: string | null;
};

export type MonthGrid = {
  year: number;
  /** 1-12, not the 0-based month a `Date` uses */
  month: number;
  /** Empty cells before day 1, 日曜始まり */
  leadingBlanks: number;
  days: CalendarDay[];
  /** Which schedule keys produced a 不明 day, for the caveat line. Deduped and
   *  in weekday order. */
  unknownDays: DayKey[];
};

/** Japanese name of a schedule key, for the caveat line. */
export function dayName(key: DayKey): string {
  return DAY_NAMES[key];
}

/** `2026年8月`. */
export function monthLabel(grid: Pick<MonthGrid, 'year' | 'month'>): string {
  return `${grid.year}年${grid.month}月`;
}

/** Whether a calendar can say anything useful about this location.
 *
 *  Mirrors その他, which renders only when non-empty. A null `weekly` means every
 *  cell would read 不明, and `permanently_closed` is already carried by the
 *  struck-through grey title - a month of shut cells adds nothing to it. */
export function showCalendarFor(h: HoursJson | null): boolean {
  return !!h && !!h.weekly && !h.permanently_closed;
}

export function shiftMonth(
  year: number, month: number, delta: number,
): { year: number; month: number } {
  // month is 1-12, so shift into a 0-based index, floor-divide, and shift back
  const zeroBased = year * 12 + (month - 1) + delta;
  return { year: Math.floor(zeroBased / 12), month: (zeroBased % 12) + 1 };
}

/** The month containing `now`, in JST. */
export function monthOf(now: Date): { year: number; month: number } {
  const [year, month] = jstDateFor(now).split('-');
  return { year: Number(year), month: Number(month) };
}

/** Every day of `year`-`month` with its openness.
 *
 *  All date arithmetic goes through `Date.UTC`, never a local-time `Date`, so the
 *  device timezone cannot shift which day is which. The day strings it builds are
 *  what `dayOpennessFor` and `@holiday-jp/holiday_jp` both want anyway - neither
 *  should ever be handed a `Date`.
 *
 *  Takes no clock: which day is "today" is the panel's concern, not the grid's.
 *  Pass `now` to `monthOf` for the opening month instead. */
export function buildMonthGrid(
  h: HoursJson, year: number, month: number,
): MonthGrid {
  // day 0 of the *next* month is the last day of this one
  const dayCount = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const leadingBlanks = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();

  const days: CalendarDay[] = [];
  const unknown = new Set<DayKey>();
  for (let dayOfMonth = 1; dayOfMonth <= dayCount; dayOfMonth += 1) {
    const date = `${year}-${pad(month)}-${pad(dayOfMonth)}`;
    const openness = dayOpennessFor(h, date);
    if (openness === 'unknown') {
      // always the calendar weekday, never 'hol': a stated 祝日 resolves to open
      // or closed, so an unknown holiday reached that state through
      // scheduleKey's weekday fallback and it is the weekday that is unstated.
      // Attributing it to 祝日 would name the wrong gap in the caveat line.
      unknown.add(weekdayKeyOn(date));
    }
    days.push({
      date,
      dayOfMonth,
      openness,
      holiday: holidayNameOn(date),
    });
  }

  return {
    year,
    month,
    leadingBlanks,
    days,
    unknownDays: WEEKDAY_KEYS.filter((key) => unknown.has(key)),
  };
}
