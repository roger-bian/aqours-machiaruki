import { linesFor } from './displayLines';
import type { Location } from './types';

/**
 * Name/stamp-number search behind the magnifying glass (panel/SearchPanel.tsx).
 *
 * A separate `.ts` module rather than component-internal because
 * `web/vitest.config.ts` matches `src/**\/*.test.ts` only - `.tsx` is
 * deliberately excluded, so logic worth pinning has to live outside the
 * component. Same reason markerColors/openStatus/displayLines are shaped this
 * way.
 */

/** Where a query hit, worst-to-best; the sort below reads these as numbers. */
const RANK_SUBSTRING = 2;
const RANK_PREFIX = 1;
const RANK_NUMBER = 0;

/**
 * Fold width and case before comparing, and drop whitespace entirely.
 *
 * NFKC is load-bearing on this data: `pipeline/app/display.py` half-widths
 * ASCII in `name` (all of it except `！`/`？`, which Love Live branding mixes on
 * purpose) while the raw `name` column stays exactly as the KML wrote it, so
 * the same shop can reach us as `ＭＩＴＯ` in one field and `MITO` in the
 * other. Whitespace goes because the display lines drop the spaces the raw name
 * carries.
 */
function fold(text: string): string {
  return text.normalize('NFKC').toLowerCase().replace(/\s+/gu, '');
}

/**
 * Both spellings of a location's name.
 *
 * The raw column and the joined display lines are searched together because
 * either alone loses matches: a query spanning the space in
 * `海鮮丼と魚河岸定食 かもめ丸` needs the raw text, and a break can consume the
 * separator it replaced (see displayLines.ts), so a query spanning that break
 * needs the joined lines.
 */
function haystacks(location: Location): string[] {
  return [fold(location.name), fold(linesFor(location, 'name').join(''))];
}

function nameRank(location: Location, query: string): number | null {
  let best: number | null = null;
  for (const hay of haystacks(location)) {
    const at = hay.indexOf(query);
    if (at === 0) return RANK_PREFIX;
    if (at > 0) best = RANK_SUBSTRING;
  }
  return best;
}

/**
 * How many leading digits of `id` the query matched, 0 for no match.
 *
 * The one place the all-digit-query rule lives, so `searchLocations` and the
 * panel's bolding can never disagree about what counted as a number hit.
 */
export function numberMatchLength(id: number, query: string): number {
  const needle = fold(query);
  if (!/^[0-9]+$/u.test(needle)) return 0;
  return String(id).startsWith(needle) ? needle.length : 0;
}

/**
 * Where `query` sits inside `text` as the user sees it: `[start, end)` into the
 * *original* string, or null.
 *
 * Matching happens on folded text but the highlight has to land on the
 * unfolded, so this folds one character at a time and keeps each output
 * character's source span. Two consequences worth knowing. Whitespace and
 * anything else `fold` drops is *inside* the returned range when the match
 * straddles it, which is what makes a query of `定食かもめ` bold across the
 * space in `海鮮丼と魚河岸定食 かもめ丸` rather than in two pieces. And
 * per-character NFKC can differ from folding the whole string (a base
 * character plus a combining dakuten composes only when folded together), so
 * this can return null on text `searchLocations` matched - the row is still
 * listed, it just renders unbolded.
 */
export function matchRange(text: string, query: string): [number, number] | null {
  const needle = fold(query);
  if (!needle) return null;

  let folded = '';
  const starts: number[] = [];
  const ends: number[] = [];
  let at = 0;
  for (const char of text) {
    for (const out of fold(char)) {
      folded += out;
      starts.push(at);
      ends.push(at + char.length);
    }
    at += char.length;
  }

  const hit = folded.indexOf(needle);
  if (hit < 0) return null;
  return [starts[hit], ends[hit + needle.length - 1]];
}

/**
 * Every location matching `query`, best match first.
 *
 * Partial matches anywhere in the name count. An all-digit query additionally
 * matches by stamp number as a *prefix* (`1` finds 1, 10-19, 100+; `12`
 * narrows) so typing progressively converges - the caller's overflow list
 * absorbs the wide early results. Uncapped: slicing at 5 is the panel's job.
 */
export function searchLocations(locations: Location[], query: string): Location[] {
  const needle = fold(query);
  if (!needle) return [];

  const ranked: { location: Location; rank: number }[] = [];
  for (const location of locations) {
    // a location can match both ways; the number hit is the stronger signal
    const rank = numberMatchLength(location.id, query) > 0
      ? RANK_NUMBER
      : nameRank(location, needle);
    if (rank != null) ranked.push({ location, rank });
  }

  // stamp number, then name prefix, then name substring - ties by stamp number,
  // which is also the KML order the markers are labelled with
  ranked.sort((a, b) => a.rank - b.rank || a.location.id - b.location.id);
  return ranked.map((entry) => entry.location);
}
