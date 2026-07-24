import os

import requests

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SECRET_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', '')

# a stalled request (observed hanging indefinitely against the live API)
# must not be able to block a pipeline run forever
TIMEOUT = 30


def _auth_headers():
    return {
        'Authorization': f'Bearer {SUPABASE_SECRET_KEY}',
        'apikey': SUPABASE_SECRET_KEY,
    }


def object_exists(path):
    url = f'{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}'
    response = requests.head(url, headers=_auth_headers(), timeout=TIMEOUT)
    return response.status_code == 200


def download_object(path):
    """Return the object's bytes, or None if it doesn't exist yet.

    Supabase Storage's object GET returns HTTP 400 (not 404) for a missing
    object, with the real status embedded in the JSON body instead
    (`{"statusCode": "404", "error": "not_found", ...}`) - confirmed
    directly against the live API, not documented anywhere obvious. A plain
    `status_code == 404` check silently never fires, so `raise_for_status()`
    ends up raising even for the ordinary "no baseline yet" bootstrap case.
    """
    url = f'{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}'
    response = requests.get(url, headers=_auth_headers(), timeout=TIMEOUT)
    if response.status_code == 404:
        return None
    if response.status_code == 400:
        try:
            if response.json().get('error') == 'not_found':
                return None
        except ValueError:
            pass
    response.raise_for_status()
    return response.content


def upload_object(path, content, content_type):
    """Upload one object to the Supabase Storage bucket (upsert) and return
    its public URL. The bucket must already be set to public - that's what
    makes the returned URL directly usable as an <img src>."""
    url = f'{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}'
    headers = {
        **_auth_headers(),
        'Content-Type': content_type,
        'x-upsert': 'true',
    }
    response = requests.post(url, headers=headers, data=content, timeout=TIMEOUT)
    response.raise_for_status()
    return public_url(path)


def public_url(path):
    return f'{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{path}'
