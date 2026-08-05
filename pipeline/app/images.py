import logging

import requests

from app.storage import TIMEOUT, list_object_keys, public_url, upload_object

logger = logging.getLogger(__name__)

# Storage key prefix for location photos. Everything else in the bucket is
# either a photo under this prefix or pipeline bookkeeping under `_pipeline/`,
# which is what makes an orphaned object identifiable by key alone. No trailing
# slash - photo_key() and list_object_keys() both paste one on, and a key set
# full of `locations//1` misses every time while looking like an empty bucket.
PHOTO_PREFIX = 'locations'


def photo_key(location_id):
    return f'{PHOTO_PREFIX}/{location_id}'


def cache_images(records):
    # Google's hosted-image CDN (mymaps.usercontent.google.com) blocks/rate-limits
    # these requests when made from a browser tab, so images are downloaded
    # once here (server-side) and uploaded to a Supabase Storage bucket, keyed
    # by the location's id - NOT a hash of the image URL. Confirmed directly:
    # Google embeds a per-request token in the photo URL, so the same placemark's
    # URL differs on every KML fetch - hashing it would never produce a stable
    # dedupe key and silently re-uploads a fresh duplicate of the same photo on
    # every single pipeline run. Storage itself is the dedupe cache (not local
    # disk, which doesn't survive a container restart) - if the object's already
    # there, skip re-fetching from Google.
    #
    # The id is the placemark's 1-based position in the KML, derived the same way
    # app/db.py derives it - from this list's order, which must therefore be KML
    # order and the complete set. The two enumerations have to agree: a photo
    # keyed on a different number than the row it belongs to would show the wrong
    # location's picture, which is why test_images.py pins them together.
    #
    # This used to hash the natural key (name|lat|lon), which meant a cosmetic
    # upstream edit - a name's line break arriving as a space, a pin nudged a few
    # metres - changed the key, missed the cache, re-fetched from Google and left
    # the old object orphaned in the bucket. The id survives all of that. The
    # trade-off: nothing invalidates the cache when a photo is genuinely
    # *replaced* upstream, so that case needs the object deleted by hand. The old
    # key didn't track photo content either, so nothing was lost here.
    #
    # One listing up front, not one existence check per record: the 136
    # sequential HEADs were ~90s of the run's wall clock against ~450ms for the
    # single list call. It is a snapshot where the old check was live, which is
    # harmless - a stale "missing" only re-fetches and re-uploads the same bytes
    # to the same key, and upload_object sends x-upsert. Nothing is added back
    # to `existing` after an upload either: positions come from enumerate(), so
    # no key is ever asked about twice in one run.
    existing = list_object_keys(PHOTO_PREFIX)
    fetched = 0
    urls_out = []
    for position, r in enumerate(records, start=1):
        url = r['_raw_img_url']
        if not url:
            urls_out.append('')
            continue

        key = photo_key(position)
        if key not in existing:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip() \
                or 'application/octet-stream'
            upload_object(key, response.content, content_type)
            fetched += 1

        urls_out.append(public_url(key))
    # the number that says whether a slow run was a cold cache or a regression
    logger.info('photos: %d already cached, %d fetched from Google',
                sum(1 for u in urls_out if u) - fetched, fetched)
    return urls_out
