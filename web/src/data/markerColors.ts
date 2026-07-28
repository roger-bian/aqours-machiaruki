import { openStatusFor } from './openStatus';
import type { FilterKey, Location, OpenStatus } from './types';

export const DEFAULT_MARKER_COLOR = '#6b7280';
export const ONE_COLLECTED_COLOR = '#f39c12';
export const BOTH_COLLECTED_COLOR = '#00a0e9';
export const MARKER_SIZE = 36;

// Fill already encodes collection progress, so open-status rides an
// independent channel: a ring around the marker. `unknown` draws no ring at
// all - a confident colour for a location whose hours aren't derivable would
// be worse than showing nothing.
export const RING_COLORS: Record<OpenStatus, string | null> = {
  open: '#22c55e',
  closing_soon: '#f59e0b',
  closed: '#ef4444',
  permanently_closed: '#000000',
  unknown: null,
};
export const RING_WIDTH = 3;

export function colorFor(loc: Pick<Location, 'stamp' | 'badge'>): string {
  const count = Number(loc.stamp) + Number(loc.badge);
  if (count === 2) return BOTH_COLLECTED_COLOR;
  if (count === 1) return ONE_COLLECTED_COLOR;
  return DEFAULT_MARKER_COLOR;
}

export function ringColorFor(status: OpenStatus): string | null {
  return RING_COLORS[status];
}

/** Filters stack (AND). One checkbox per concept rather than per field, so
 *  ticking both asks "still need something here *and* it's open right now" -
 *  which is the actual walking-around-Numazu question. */
export function matchesFilters(
  loc: Pick<Location, 'stamp' | 'badge' | 'hours_json'>,
  activeFilters: Set<FilterKey>,
  now: Date,
): boolean {
  if (activeFilters.has('uncollected') && loc.stamp && loc.badge) return false;
  if (activeFilters.has('open_now')) {
    const status = openStatusFor(loc.hours_json, now);
    // closing_soon is still open, just not for long
    if (status !== 'open' && status !== 'closing_soon') return false;
  }
  return true;
}
