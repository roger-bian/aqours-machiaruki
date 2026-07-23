import { useEffect, useState } from 'react';
import type { Location } from '../data/types';
import { API_BASE, authHeaders } from '../data/supabaseRest';

export function useLocations() {
  const [locations, setLocations] = useState<Location[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetch(`${API_BASE}/locations`, { headers: authHeaders() })
      .then((res) => {
        if (!res.ok) throw new Error(`GET /locations failed: ${res.status}`);
        return res.json();
      })
      .then((data: Location[]) => {
        if (!cancelled) setLocations(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { locations, setLocations, loading, error };
}
