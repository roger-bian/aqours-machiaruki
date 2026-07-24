import os

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

AUTH0_DOMAIN = os.environ['AUTH0_DOMAIN']
AUTH0_CLIENT_ID = os.environ['AUTH0_CLIENT_ID']
# comma-separated designated emails allowed to trigger this endpoint - kept
# out of source, matching the same allowlist enforced by the Auth0 Action
ALLOWED_EMAILS = {e.strip() for e in os.environ['ALLOWED_EMAILS'].split(',') if e.strip()}

_jwks_client = PyJWKClient(f'https://{AUTH0_DOMAIN}/.well-known/jwks.json')


def verify_auth0_token(authorization: str = Header(None)):
    """FastAPI dependency gating POST /pipeline/run. The frontend's
    "データ更新" button sends the same live Auth0 ID token already used for
    Supabase requests; this verifies it directly against Auth0's JWKS
    (PyJWKClient handles fetching/caching/kid-selection/rotation) rather
    than relying on a static shared secret, which would stop being a real
    secret once baked into the public frontend bundle.
    """
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='missing bearer token')
    token = authorization.removeprefix('Bearer ')
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=['RS256'],
            audience=AUTH0_CLIENT_ID, issuer=f'https://{AUTH0_DOMAIN}/',
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail='invalid token')
    if claims.get('email') not in ALLOWED_EMAILS:
        raise HTTPException(status_code=401, detail='unauthorized')
