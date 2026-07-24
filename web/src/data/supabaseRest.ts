// points at Supabase's REST API (PostgREST under the hood) - swap these
// two env vars to point at a different project without touching any
// fetch/PATCH call sites
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:3001';
const PUBLISHABLE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

// Populated by AuthGate once Auth0 login completes - Supabase is configured
// as a Third-Party Auth provider trusting this Auth0 tenant directly, so
// the live ID token (not the static publishable key) is what RLS actually
// evaluates for the `authenticated` role.
let getIdToken: (() => Promise<string>) | null = null;

export function registerIdTokenGetter(fn: () => Promise<string>) {
  getIdToken = fn;
}

export async function authHeaders(extra: Record<string, string> = {}): Promise<Record<string, string>> {
  const token = getIdToken ? await getIdToken() : null;
  return token
    ? { apikey: PUBLISHABLE_KEY, Authorization: `Bearer ${token}`, ...extra }
    : extra;
}
