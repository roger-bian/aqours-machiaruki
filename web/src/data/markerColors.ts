import type { Location, FilterKey } from './types';

export const DEFAULT_MARKER_COLOR = '#636efa';
export const ONE_COLLECTED_COLOR = '#f39c12';
export const BOTH_COLLECTED_COLOR = '#2ecc71';
export const MARKER_SIZE = 36;

export function colorFor(loc: Pick<Location, 'stamp' | 'badge'>): string {
  const count = Number(loc.stamp) + Number(loc.badge);
  if (count === 2) return BOTH_COLLECTED_COLOR;
  if (count === 1) return ONE_COLLECTED_COLOR;
  return DEFAULT_MARKER_COLOR;
}

export function matchesFilters(
  loc: Pick<Location, 'stamp' | 'badge'>,
  activeFilters: Set<FilterKey>,
): boolean {
  if (activeFilters.size === 0) return true;
  const stampMatch = activeFilters.has('stamp_missing') && !loc.stamp;
  const badgeMatch = activeFilters.has('badge_missing') && !loc.badge;
  return stampMatch || badgeMatch;
}
