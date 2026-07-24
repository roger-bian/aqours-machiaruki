import hashlib

import requests

from app.storage import TIMEOUT, object_exists, public_url, upload_object


def cache_images(records):
    # Google's hosted-image CDN (mymaps.usercontent.google.com) blocks/rate-limits
    # these requests when made from a browser tab, so images are downloaded
    # once here (server-side) and uploaded to a Supabase Storage bucket, keyed
    # by the location's natural key (name/lat/lon) - NOT a hash of the image
    # URL. Confirmed directly: Google embeds a per-request token in the photo
    # URL, so the same placemark's URL differs on every KML fetch - hashing it
    # would never produce a stable dedupe key and silently re-uploads a fresh
    # duplicate of the same photo on every single pipeline run. Storage itself
    # is the dedupe cache (not local disk, which doesn't survive a container
    # restart) - if the object's already there, skip re-fetching from Google.
    urls_out = []
    for r in records:
        url = r['_raw_img_url']
        if not url:
            urls_out.append('')
            continue

        digest = hashlib.sha1(f"{r['name']}|{r['lat']}|{r['lon']}".encode()).hexdigest()
        if not object_exists(digest):
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip() \
                or 'application/octet-stream'
            upload_object(digest, response.content, content_type)

        urls_out.append(public_url(digest))
    return urls_out
