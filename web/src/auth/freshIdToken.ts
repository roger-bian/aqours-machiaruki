type Auth0TokenMethods = {
  getAccessTokenSilently: () => Promise<unknown>;
  getIdTokenClaims: () => Promise<{ __raw?: string } | undefined>;
  loginWithRedirect: (opts?: { authorizationParams?: { connection?: string } }) => Promise<void>;
};

// getIdTokenClaims() is a passive cache read - it returns whatever ID token is
// cached even if long expired. getAccessTokenSilently() is what actually checks
// expiry and uses the refresh token to mint a fresh one; calling it first (and
// discarding its result) forces that refresh as a side effect, so the
// getIdTokenClaims() read right after is guaranteed fresh. If the refresh token
// itself is gone/revoked, getAccessTokenSilently() throws (login_required) -
// caught here and routed to a real re-login instead of surfacing a 401 to the
// caller.
export async function getFreshIdToken(auth0: Auth0TokenMethods): Promise<string> {
  try {
    await auth0.getAccessTokenSilently();
  } catch {
    await auth0.loginWithRedirect({ authorizationParams: { connection: 'google-oauth2' } });
    throw new Error('Auth0 session expired - redirecting to login');
  }
  const claims = await auth0.getIdTokenClaims();
  if (!claims?.__raw) throw new Error('Missing Auth0 ID token');
  return claims.__raw;
}
