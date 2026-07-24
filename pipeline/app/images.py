import hashlib

import requests

from app.storage import object_exists, public_url, upload_object


def cache_images(urls):
    # Google's hosted-image CDN (mymaps.usercontent.google.com) blocks/rate-limits
    # these requests when made from a browser tab, so images are downloaded
    # once here (server-side) and uploaded to a Supabase Storage bucket, keyed
    # by a hash of their source URL. Storage itself is the dedupe cache (not
    # local disk, which doesn't survive a container restart) - if the object
    # is already there, skip re-fetching from Google entirely.
    urls_out = []
    for url in urls:
        if not url:
            urls_out.append('')
            continue

        digest = hashlib.sha1(url.encode()).hexdigest()
        if not object_exists(digest):
            response = requests.get(url)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip() \
                or 'application/octet-stream'
            upload_object(digest, response.content, content_type)

        urls_out.append(public_url(digest))
    return urls_out
