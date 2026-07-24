import { useCallback, useEffect, useState } from 'react';
import type { Location } from '../data/types';
import { API_BASE, authHeaders } from '../data/supabaseRest';

export function useLocations() {
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/locations`, { headers: await authHeaders() });
      if (!res.ok) throw new Error(`GET /locations failed: ${res.status}`);
      const data: Location[] = await res.json();
      setLocations(data);
      setError(null);
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  // called when a marker's detail panel opens - re-syncs just that one
  // row's collection state, since another device may have toggled it
  // since this page's initial load without this page ever reloading
  const refreshOne = useCallback(async (id: number) => {
    try {
      const res = await fetch(
        `${API_BASE}/locations?id=eq.${id}&select=id,stamp,badge`,
        { headers: await authHeaders() },
      );
      if (!res.ok) return;
      const [fresh] = await res.json();
      if (!fresh) return;
      setLocations((prev) =>
        prev.map((loc) => (loc.id === fresh.id ? { ...loc, stamp: fresh.stamp, badge: fresh.badge } : loc)),
      );
    } catch {
      // best-effort - a stale local value is what we already had, not worse
    }
  }, []);

  return { locations, setLocations, loading, error, refetch, refreshOne };
}
