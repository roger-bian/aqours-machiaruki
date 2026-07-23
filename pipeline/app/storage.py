import os

import requests

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SECRET_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', '')


def upload_image(filename, content, content_type):
    """Upload one image to the Supabase Storage bucket (upsert) and return
    its public URL. The bucket must already be set to public - that's what
    makes the returned URL directly usable as an <img src>."""
    url = f'{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{filename}'
    headers = {
        'Authorization': f'Bearer {SUPABASE_SECRET_KEY}',
        'apikey': SUPABASE_SECRET_KEY,
        'Content-Type': content_type,
        'x-upsert': 'true',
    }
    response = requests.post(url, headers=headers, data=content)
    response.raise_for_status()
    return f'{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{filename}'
