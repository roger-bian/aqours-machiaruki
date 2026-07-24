import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { registerIdTokenGetter } from '../data/supabaseRest';

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
  const { isLoading, isAuthenticated, loginWithRedirect, getIdTokenClaims, error } = useAuth0();

  useEffect(() => {
    if (!isAuthenticated) return;
    registerIdTokenGetter(async () => {
      const claims = await getIdTokenClaims();
      if (!claims?.__raw) throw new Error('Missing Auth0 ID token');
      return claims.__raw;
    });
  }, [isAuthenticated, getIdTokenClaims]);

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
