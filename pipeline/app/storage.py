import os

import requests

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SECRET_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', '')

# a stalled request (observed hanging indefinitely against the live API)
# must not be able to block a pipeline run forever
TIMEOUT = 30

# how many objects to ask for per list call. Not a promise: the server is free
# to return fewer, which is why the paging loop below stops on an *empty* page
LIST_PAGE_SIZE = 1000


def _auth_headers():
    return {
        'Authorization': f'Bearer {SUPABASE_SECRET_KEY}',
        'apikey': SUPABASE_SECRET_KEY,
    }


def list_object_keys(prefix):
    """Every existing object key under `prefix`, as a set. `prefix` must not
    end in a slash - the key is rebuilt as f'{prefix}/{name}'.

    Replaces one HEAD per key: 136 objects went from ~90s of sequential
    existence checks (a fresh TLS handshake each) to ~450ms.

    Two quirks of this endpoint, both confirmed against the live API, neither
    obvious from the docs. `name` comes back *relative* to the prefix ("1",
    not "locations/1") - callers want full keys, so the prefix is pasted back
    on. And pseudo-folders are listed alongside real objects, distinguishable
    only by a null `id`; a folder entry would otherwise become a key that no
    object has.

    Stops on an empty page rather than a short one. `limit=1000` returning 136
    rows proves the server's cap is >=136, not >=1000 - a cap anywhere in
    between would silently truncate a grown bucket. One extra round trip buys
    immunity, and a truncated set is invisible: it just re-downloads every
    photo it failed to see from a CDN that rate-limits repeats.
    """
    url = f'{SUPABASE_URL}/storage/v1/object/list/{SUPABASE_BUCKET}'
    keys = set()
    offset = 0
    while True:
        response = requests.post(
            url,
            headers=_auth_headers(),
            json={'prefix': prefix, 'limit': LIST_PAGE_SIZE, 'offset': offset},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        page = response.json()
        if not page:
            return keys
        keys.update(f'{prefix}/{entry["name"]}'
                    for entry in page if entry.get('id') is not None)
        # by len(page), not LIST_PAGE_SIZE - identical for a full page, correct
        # if the server ever returns fewer than asked for
        offset += len(page)


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
