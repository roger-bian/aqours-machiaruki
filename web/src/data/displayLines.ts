import type { DisplayField, Location } from './types';

/**
 * The lines to render for one of the four freeform text fields.
 *
 * Line breaking is decided in the pipeline (`pipeline/app/display.py`) and
 * stored in `display_json`, because where Japanese text breaks is a semantic
 * call no rule settles - see CLAUDE.md. This is the single fallback point for a
 * row the pipeline hasn't reached yet (a `display_json` still null right after
 * the column was added): render the raw text unbroken and let CSS wrap it,
 * rather than repeating `?? [location[field]]` at four call sites.
 */
export function linesFor(location: Location, field: DisplayField): string[] {
  const lines = location.display_json?.[field];
  if (lines && lines.length > 0) return lines;
  const raw = location[field];
  return raw ? [raw] : [];
}

/** The その他 section, empty for most locations. */
export function extraLines(location: Location): string[] {
  return location.display_json?.extra ?? [];
}
