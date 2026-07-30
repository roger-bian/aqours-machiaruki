import { useEffect, useMemo, useState } from 'react';
import type { Map as LeafletMap } from 'leaflet';
import { MapView } from './map/MapView';
import { DetailPanel } from './panel/DetailPanel';
import { FilterPanel } from './panel/FilterPanel';
import { SearchPanel } from './panel/SearchPanel';
import { RefreshDataButton } from './panel/RefreshDataButton';
import { ClockPanel } from './panel/ClockPanel';
import { Backdrop } from './panel/Backdrop';
import { useLocations } from './hooks/useLocations';
import { useToggleCollected } from './hooks/useToggleCollected';
import { useUserLocation } from './hooks/useUserLocation';
import { matchesFilters } from './data/markerColors';
import type { FilterKey } from './data/types';

const ACTIVE_FILTERS_STORAGE_KEY = 'activeFilters';
const FILTER_KEYS: FilterKey[] = ['uncollected', 'open_now'];

// how often the open/closed evaluation re-runs; a minute is finer than any
// closing time in the data and cheap for ~136 pure comparisons
const CLOCK_TICK_MS = 60_000;

function loadStoredFilters(): Set<FilterKey> {
  try {
    const raw = localStorage.getItem(ACTIVE_FILTERS_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((key): key is FilterKey => FILTER_KEYS.includes(key)));
  } catch {
    return new Set();
  }
}

function App() {
  const { locations, setLocations, loading, error, refreshOne } = useLocations();
  const { toggle: toggleCollected, isPending } = useToggleCollected(setLocations);
  const { position: userPosition, locate, locating } = useUserLocation();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [activeFilters, setActiveFilters] = useState<Set<FilterKey>>(loadStoredFilters);
  const [now, setNow] = useState(() => new Date());
  const [map, setMap] = useState<LeafletMap | null>(null);

  // without this the marker rings and the 営業中のみ filter would both freeze
  // at page-load time - the memo below and markerIcon's cache are only
  // invalidated when `now` changes
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), CLOCK_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    localStorage.setItem(ACTIVE_FILTERS_STORAGE_KEY, JSON.stringify([...activeFilters]));
  }, [activeFilters]);

  useEffect(() => {
    if (selectedId != null) refreshOne(selectedId);
  }, [selectedId, refreshOne]);

  const visibleLocations = useMemo(
    () => locations.filter((loc) => matchesFilters(loc, activeFilters, now)),
    [locations, activeFilters, now],
  );

  // search spans every location, so it needs to know which pins the filters
  // have taken off the map in order to flag those suggestions
  const visibleIds = useMemo(
    () => new Set(visibleLocations.map((loc) => loc.id)),
    [visibleLocations],
  );

  const selectedLocation = useMemo(
    () => locations.find((loc) => loc.id === selectedId) ?? null,
    [locations, selectedId],
  );

  function onToggleFilter(key: FilterKey) {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  if (loading) return <div style={{ padding: 16 }}>Loading…</div>;
  if (error) return <div style={{ padding: 16 }}>Failed to load: {error.message}</div>;

  return (
    <>
      <MapView
        locations={visibleLocations}
        onSelect={setSelectedId}
        userPosition={userPosition}
        onLocate={locate}
        locating={locating}
        now={now}
        onMapReady={setMap}
      />
      <SearchPanel
        locations={locations}
        visibleIds={visibleIds}
        map={map}
        onSelect={setSelectedId}
      />
      <FilterPanel activeFilters={activeFilters} onToggle={onToggleFilter} />
      <RefreshDataButton />
      <ClockPanel />
      {selectedLocation && (
        <>
          <Backdrop onClose={() => setSelectedId(null)} />
          <DetailPanel
            location={selectedLocation}
            now={now}
            stampPending={isPending(selectedLocation.id, 'stamp')}
            badgePending={isPending(selectedLocation.id, 'badge')}
            onToggleStamp={() => toggleCollected(selectedLocation.id, 'stamp', selectedLocation.stamp)}
            onToggleBadge={() => toggleCollected(selectedLocation.id, 'badge', selectedLocation.badge)}
            onClose={() => setSelectedId(null)}
          />
        </>
      )}
    </>
  );
}

export default App;
