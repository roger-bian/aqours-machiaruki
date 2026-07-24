import os

import requests

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SECRET_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', '')


def _auth_headers():
    return {
        'Authorization': f'Bearer {SUPABASE_SECRET_KEY}',
        'apikey': SUPABASE_SECRET_KEY,
    }


def object_exists(path):
    url = f'{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}'
    response = requests.head(url, headers=_auth_headers())
    return response.status_code == 200


def download_object(path):
    """Return the object's bytes, or None if it doesn't exist yet."""
    url = f'{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}'
    response = requests.get(url, headers=_auth_headers())
    if response.status_code == 404:
        return None
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
    response = requests.post(url, headers=headers, data=content)
    response.raise_for_status()
    return public_url(path)


def public_url(path):
    return f'{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{path}'
