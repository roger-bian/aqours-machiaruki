import { describe, expect, it, vi } from 'vitest';
import { getFreshIdToken } from './freshIdToken';

const nowSeconds = () => Math.floor(Date.now() / 1000);

// Stands in for Auth0 SPA-JS's split cache: getIdTokenClaims() reads an entry
// with no expiry of its own, and getAccessTokenSilently() only mints a new ID
// token when the access-token entry is stale or cacheMode is 'off'.
function fakeAuth0(opts: { idTokenExp: number; accessCacheWarm: boolean; refreshTokenValid?: boolean }) {
  const { idTokenExp, accessCacheWarm, refreshTokenValid = true } = opts;
  let exp = idTokenExp;
  let raw = 'stale-token';

  return {
    exchanges: 0,
    getAccessTokenSilently: vi.fn(async function (this: void, o?: { cacheMode?: string }) {
      const usesCache = o?.cacheMode !== 'off';
      if (usesCache && accessCacheWarm) return 'cached-access-token'; // no network, ID token untouched
      if (!refreshTokenValid) throw new Error('login_required');
      exp = nowSeconds() + 36000;
      raw = 'fresh-token';
      return 'new-access-token';
    }),
    getIdTokenClaims: vi.fn(async () => ({ __raw: raw, exp })),
    loginWithRedirect: vi.fn(async () => {}),
  };
}

describe('getFreshIdToken', () => {
  it('returns the cached token untouched when it is still valid', async () => {
    const auth0 = fakeAuth0({ idTokenExp: nowSeconds() + 3600, accessCacheWarm: true });
    expect(await getFreshIdToken(auth0)).toBe('stale-token');
    // no round-trip: this runs on every Supabase read/write and pipeline poll
    expect(auth0.getAccessTokenSilently).not.toHaveBeenCalled();
  });

  it('forces a cache-bypassing exchange when the ID token expired but the access-token cache is warm', async () => {
    const auth0 = fakeAuth0({ idTokenExp: nowSeconds() - 40000, accessCacheWarm: true });
    expect(await getFreshIdToken(auth0)).toBe('fresh-token');
    expect(auth0.getAccessTokenSilently).toHaveBeenCalledWith({ cacheMode: 'off' });
  });

  it('refreshes a token inside the expiry skew rather than letting it expire mid-flight', async () => {
    const auth0 = fakeAuth0({ idTokenExp: nowSeconds() + 30, accessCacheWarm: true });
    expect(await getFreshIdToken(auth0)).toBe('fresh-token');
  });

  it('redirects to login when the refresh token is gone, instead of surfacing a 401', async () => {
    const auth0 = fakeAuth0({ idTokenExp: nowSeconds() - 40000, accessCacheWarm: true, refreshTokenValid: false });
    await expect(getFreshIdToken(auth0)).rejects.toThrow('Auth0 session expired');
    expect(auth0.loginWithRedirect).toHaveBeenCalledWith({
      authorizationParams: { connection: 'google-oauth2' },
    });
  });

  it('never returns a token it knows is expired', async () => {
    const auth0 = {
      getAccessTokenSilently: vi.fn(async () => 'access'),
      // a refresh that somehow yields a still-expired token (skewed device clock)
      getIdTokenClaims: vi.fn(async () => ({ __raw: 'stale-token', exp: nowSeconds() - 40000 })),
      loginWithRedirect: vi.fn(async () => {}),
    };
    await expect(getFreshIdToken(auth0)).rejects.toThrow('already-expired');
  });

  it('rejects when no ID token is cached at all', async () => {
    const auth0 = {
      getAccessTokenSilently: vi.fn(async () => 'access'),
      getIdTokenClaims: vi.fn(async () => undefined),
      loginWithRedirect: vi.fn(async () => {}),
    };
    await expect(getFreshIdToken(auth0)).rejects.toThrow('Missing Auth0 ID token');
  });
});
