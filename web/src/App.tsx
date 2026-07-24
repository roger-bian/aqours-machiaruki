import { useEffect, useMemo, useState } from 'react';
import { MapView } from './map/MapView';
import { DetailPanel } from './panel/DetailPanel';
import { FilterPanel } from './panel/FilterPanel';
import { RefreshDataButton } from './panel/RefreshDataButton';
import { Backdrop } from './panel/Backdrop';
import { useLocations } from './hooks/useLocations';
import { useToggleCollected } from './hooks/useToggleCollected';
import { useUserLocation } from './hooks/useUserLocation';
import { matchesFilters } from './data/markerColors';
import type { FilterKey } from './data/types';

function App() {
  const { locations, setLocations, loading, error, refreshOne } = useLocations();
  const { toggle: toggleCollected, isPending } = useToggleCollected(setLocations);
  const userPosition = useUserLocation();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [activeFilters, setActiveFilters] = useState<Set<FilterKey>>(new Set());

  useEffect(() => {
    if (selectedId != null) refreshOne(selectedId);
  }, [selectedId, refreshOne]);

  const visibleLocations = useMemo(
    () => locations.filter((loc) => matchesFilters(loc, activeFilters)),
    [locations, activeFilters],
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
      <MapView locations={visibleLocations} onSelect={setSelectedId} userPosition={userPosition} />
      <FilterPanel activeFilters={activeFilters} onToggle={onToggleFilter} />
      <RefreshDataButton />
      {selectedLocation && (
        <>
          <Backdrop onClose={() => setSelectedId(null)} />
          <DetailPanel
            location={selectedLocation}
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
