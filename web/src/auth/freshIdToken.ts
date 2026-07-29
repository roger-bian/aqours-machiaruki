type IdTokenClaims = { __raw?: string; exp?: number };

type Auth0TokenMethods = {
  getAccessTokenSilently: (opts?: { cacheMode?: 'on' | 'off' | 'cache-only' }) => Promise<unknown>;
  getIdTokenClaims: () => Promise<IdTokenClaims | undefined>;
  loginWithRedirect: (opts?: { authorizationParams?: { connection?: string } }) => Promise<void>;
};

// refresh a little early so a token expiring mid-flight doesn't go out
const EXPIRY_SKEW_SECONDS = 60;

function isExpired(claims: IdTokenClaims | undefined, skewSeconds: number): boolean {
  if (!claims?.exp) return true;
  return claims.exp - skewSeconds <= Math.floor(Date.now() / 1000);
}

// Use this for every ID token - never getIdTokenClaims() directly. Auth0
// SPA-JS caches the ID token with no expiry, so getIdTokenClaims() returns it
// long after it expired, and getAccessTokenSilently() only exchanges once the
// separately-cached *access* token goes stale (different, longer lifetime).
// Hence the explicit `exp` check plus `cacheMode: 'off'` to force an exchange;
// skipping it when the token is still valid keeps Auth0 out of the hot path.
// Throws on a dead refresh token after redirecting to login.
export async function getFreshIdToken(auth0: Auth0TokenMethods): Promise<string> {
  let claims = await auth0.getIdTokenClaims();

  if (isExpired(claims, EXPIRY_SKEW_SECONDS)) {
    try {
      await auth0.getAccessTokenSilently({ cacheMode: 'off' });
    } catch {
      await auth0.loginWithRedirect({ authorizationParams: { connection: 'google-oauth2' } });
      throw new Error('Auth0 session expired - redirecting to login');
    }
    claims = await auth0.getIdTokenClaims();
  }

  if (!claims?.__raw) throw new Error('Missing Auth0 ID token');
  // still expired right after a forced refresh = device clock is off
  if (isExpired(claims, 0)) throw new Error('Auth0 returned an already-expired ID token - check the device clock');
  return claims.__raw;
}
