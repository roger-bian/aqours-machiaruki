export type DayKey = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun' | 'hol';

/** `[startMinute, endMinute]` from midnight - 600 is 10:00. An end past 1440
 *  means the shift runs into the next day (`11:00~26:00` is `[660, 1560]`). */
export type Interval = [number, number];

/** Mirrors the `hours_json` jsonb column, written by pipeline/app/hours.py.
 *  PostgREST returns jsonb as real nested JSON, so this arrives parsed. */
export type HoursJson = {
  /** null when the source stated no hours at all */
  weekly: Record<DayKey, Interval[]> | null;
  closed: DayKey[];
  closed_nth: { day: DayKey; nth: number[] }[];
  /** `MM-DD`, e.g. the 年末年始 shutdown */
  closed_dates: string[];
  always_open: boolean;
  /** 不定休 / 臨時休館 - daily hours are known but closures are not */
  irregular: boolean;
  permanently_closed: boolean;
  confidence: 'verified' | 'manual' | 'auto';
  notes: string[];
};

export type OpenStatus =
  | 'open'
  | 'closing_soon'
  | 'closed'
  | 'permanently_closed'
  | 'unknown';

/** The four fields whose line breaks are decided in the pipeline. */
export type DisplayField = 'name' | 'address' | 'hours' | 'holidays';

/**
 * Pre-broken lines from pipeline/app/display.py, mirrored by
 * `CONTRACT_KEYS` in pipeline/tests/test_display_golden.py. One line per
 * `<br/>`; the text columns stay faithful to the KML, so the address's Maps
 * query still uses the unbroken string.
 */
export type DisplayJson = Record<DisplayField, string[]> & {
  /** その他: parking, URLs, stamp placement, end-of-rally markers */
  extra: string[];
  confidence: 'verified' | 'auto';
};

export type Location = {
  id: number;
  name: string;
  lat: number;
  lon: number;
  member: string;
  address: string;
  hours: string;
  holidays: string;
  hours_json: HoursJson | null;
  display_json: DisplayJson | null;
  img_url: string;
  // collection state - the frontend is the only writer of these two columns
  stamp: boolean;
  badge: boolean;
};

export type FilterKey = 'uncollected' | 'open_now';
