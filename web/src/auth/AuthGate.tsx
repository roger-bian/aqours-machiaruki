import type { ReactNode } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { registerIdTokenGetter } from '../data/supabaseRest';
import { getFreshIdToken } from './freshIdToken';

const GATE_STYLE: React.CSSProperties = {
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 16,
};

// Auth0 authenticates (Google login, restricted to the owner's email via an
// Auth0 Action) and Supabase trusts this tenant directly as a Third-Party
// Auth provider - the ID token fetched here is what RLS evaluates, not a
// static key. Nothing behind this gate renders until login succeeds.
export function AuthGate({ children }: { children: ReactNode }) {
  const { isLoading, isAuthenticated, loginWithRedirect, getAccessTokenSilently, getIdTokenClaims, error } =
    useAuth0();

  // Registered synchronously during render, not in a useEffect: React fires
  // child effects before parent effects, so a useEffect here would race
  // useLocations' own mount-time fetch - its very first request could go out
  // with no token registered yet, sent unauthenticated, and get a 401 once
  // RLS requires the `authenticated` role. Dev's <StrictMode> double-invokes
  // effects and happened to mask this (the second pass runs after
  // registration completes) - production builds don't get that safety net.
  //
  // getFreshIdToken (not a plain getIdTokenClaims() read) matters here: after
  // >1 day away, isAuthenticated above is often true from a stale cached user
  // even though the cached ID token has long since expired (Auth0 SPA-JS's
  // mount-time checkSession() only refreshes if a 1-day cookie is still
  // present - see auth0-spa-js constants.ts DEFAULT_SESSION_CHECK_EXPIRY_DAYS).
  // getFreshIdToken forces a real refresh-token-backed refresh instead.
  if (isAuthenticated) {
    registerIdTokenGetter(() => getFreshIdToken({ getAccessTokenSilently, getIdTokenClaims, loginWithRedirect }));
  }

  if (isLoading) {
    return (
      <div style={GATE_STYLE}>
        <span className="spinner" />
      </div>
    );
  }

  if (error) {
    return <div style={{ padding: 16 }}>Login failed: {error.message}</div>;
  }

  if (!isAuthenticated) {
    return (
      <div style={GATE_STYLE}>
        <button
          onClick={() =>
            loginWithRedirect({ authorizationParams: { connection: 'google-oauth2' } })
          }
        >
          Log in with Google
        </button>
      </div>
    );
  }

  return <>{children}</>;
}
