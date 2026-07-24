import { useCallback, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { Location } from '../data/types';
import { API_BASE, authHeaders } from '../data/supabaseRest';

function key(id: number, field: 'stamp' | 'badge') {
  return `${id}:${field}`;
}

// Writes straight to Postgres via Supabase's REST API, updating the
// passed-in `locations` array in place so the UI (marker color, checkbox)
// reflects the change immediately, with a rollback if the write fails.
// Also tracks which (id, field) pairs currently have a write in flight, so
// the UI can disable/spin the checkbox and rapid re-clicks on the same
// checkbox can't fire overlapping requests.
export function useToggleCollected(setLocations: Dispatch<SetStateAction<Location[]>>) {
  // a ref (not state) guards the synchronous "already in flight?" check -
  // state alone would race, since the setter that adds a key wouldn't be
  // visible yet on the very next click within the same tick
  const pendingRef = useRef<Set<string>>(new Set());
  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set());

  const toggle = useCallback(
    (id: number, field: 'stamp' | 'badge', current: boolean) => {
      const k = key(id, field);
      if (pendingRef.current.has(k)) return;

      pendingRef.current.add(k);
      setPendingKeys(new Set(pendingRef.current));

      const next = !current;
      setLocations((prev) => prev.map((loc) => (loc.id === id ? { ...loc, [field]: next } : loc)));

      authHeaders({ 'Content-Type': 'application/json', Prefer: 'return=minimal' })
        .then((headers) =>
          fetch(`${API_BASE}/locations?id=eq.${id}`, {
            method: 'PATCH',
            headers,
            body: JSON.stringify({ [field]: next }),
          }),
        )
        .then((res) => {
          if (!res.ok) throw new Error(`PATCH /locations failed: ${res.status}`);
        })
        .catch(() => {
          setLocations((prev) =>
            prev.map((loc) => (loc.id === id ? { ...loc, [field]: current } : loc)),
          );
        })
        .finally(() => {
          pendingRef.current.delete(k);
          setPendingKeys(new Set(pendingRef.current));
        });
    },
    [setLocations],
  );

  const isPending = useCallback((id: number, field: 'stamp' | 'badge') => pendingKeys.has(key(id, field)), [pendingKeys]);

  return { toggle, isPending };
}
