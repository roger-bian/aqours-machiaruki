// points at Supabase's REST API (PostgREST under the hood) - swap these
// two env vars to point at a different project without touching any
// fetch/PATCH call sites
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:3001';
const PUBLISHABLE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return PUBLISHABLE_KEY
    ? { apikey: PUBLISHABLE_KEY, Authorization: `Bearer ${PUBLISHABLE_KEY}`, ...extra }
    : extra;
}
