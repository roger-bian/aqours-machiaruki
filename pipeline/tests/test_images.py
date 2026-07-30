"""Tests for app/images.py.

`cache_images` uses Supabase Storage itself as its dedupe cache, keyed on each
location's id - the placemark's 1-based position in the KML. Two things are
pinned here, both of them bugs this module has already had:

1. The key must not depend on the photo URL. Google embeds a per-request token
   in every photo URL, so it differs on every KML fetch. Keying on it produced
   a cache that never hit, silently re-uploading a duplicate of every photo on
   every single run.
2. The key must not depend on the location's text or coordinates either. The
   key used to be sha1(name|lat|lon), so a cosmetic upstream edit - a name's
   line break arriving as a space, a pin nudged a few metres - moved the key,
   missed the cache, re-fetched from Google's rate-limiting CDN and orphaned
   the old object in the bucket.

Note the patch targets. app/images.py does `from app.storage import ...`, which
binds those names into its own module namespace at import time, so patching
`app.storage.object_exists` has no effect at all.
"""
import requests

from app import images


class Response:
    def __init__(self, content=b'\xff\xd8jpeg', headers=None):
        self.content = content
        self.headers = headers if headers is not None else {'Content-Type': 'image/jpeg'}

    def raise_for_status(self):
        pass


def record(name='ゲーマーズ沼津店', lat=35.10157, lon=138.856807, img_url='https://g/1'):
    return {'name': name, 'lat': lat, 'lon': lon, '_raw_img_url': img_url}


def stub_storage(monkeypatch, exists=False):
    """Returns the call log; `uploads` is a list of (key, content, content_type)."""
    calls = {'exists': [], 'uploads': [], 'fetched': []}

    def fake_get(url, timeout):
        calls['fetched'].append(url)
        return Response()

    monkeypatch.setattr(images, 'object_exists', lambda key: (calls['exists'].append(key), exists)[1])
    monkeypatch.setattr(images, 'upload_object',
                        lambda key, content, ct: calls['uploads'].append((key, content, ct)))
    monkeypatch.setattr(images, 'public_url', lambda key: f'https://storage/{key}')
    monkeypatch.setattr(requests, 'get', fake_get)
    return calls


# --- what the key is made of ----------------------------------------------

def test_keys_are_the_one_based_position(monkeypatch):
    calls = stub_storage(monkeypatch)

    images.cache_images([record(), record(), record()])

    assert calls['exists'] == ['locations/1', 'locations/2', 'locations/3']


def test_key_is_the_id_not_the_photo_url(monkeypatch):
    """The regression test for the re-upload-every-run bug. Google re-tokenizes
    the photo URL on every KML fetch, so the same location must still land on the
    same Storage object."""
    calls = stub_storage(monkeypatch)

    first = images.cache_images([record(img_url='https://g/token-A')])
    second = images.cache_images([record(img_url='https://g/token-B')])

    assert first == second
    assert calls['exists'][0] == calls['exists'][1]


def test_key_survives_a_rename_or_a_moved_pin(monkeypatch):
    """The regression test for the orphaned-object bug: under the old
    sha1(name|lat|lon) key, an upstream edit this cosmetic changed the key,
    re-fetched the identical photo and left the old object behind forever."""
    calls = stub_storage(monkeypatch, exists=True)

    before = images.cache_images([record(name='海鮮丼と魚河岸定食\nかもめ丸', lat=35.1, lon=138.8)])
    after = images.cache_images([record(name='海鮮丼と魚河岸定食 かもめ丸', lat=35.2, lon=138.9)])

    assert before == after
    assert calls['fetched'] == []


def test_distinct_positions_get_distinct_keys(monkeypatch):
    """Identical text and coordinates - the old key would have collapsed all
    three onto one object."""
    stub_storage(monkeypatch)

    urls = images.cache_images([record(), record(), record()])

    assert len(set(urls)) == 3


def test_the_key_counts_records_not_photos(monkeypatch):
    """Position is the record's place in the KML, so a location with no photo
    still consumes its number. Counting only the records that have a photo would
    hand every later location the previous one's picture."""
    calls = stub_storage(monkeypatch)

    urls = images.cache_images([
        record(img_url=''),
        record(img_url='https://g/photo'),
    ])

    assert calls['exists'] == ['locations/2']
    assert urls == ['', 'https://storage/locations/2']


def test_keys_line_up_with_the_ids_db_will_assign(monkeypatch, placemarks):
    """app/images.py and app/db.py derive the id independently, both from this
    list's order. If the two ever disagreed, a location would render another
    location's photo - so pin them against each other over the real fixture."""
    from app.db import upsert_locations
    from app.main import _build_records
    import psycopg2

    records = _build_records(placemarks)
    calls = stub_storage(monkeypatch)
    keys = [images.photo_key(i) for i in range(1, len(records) + 1)]
    assert images.cache_images(records) == [f'https://storage/{k}' for k in keys]

    executed = []

    class Cursor:
        def execute(self, sql, params):
            executed.append(params)

        def fetchone(self):
            return (True,)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(psycopg2, 'connect', lambda url: Connection())
    for r in records:
        r['img_url'] = 'https://storage/stub'
        del r['_raw_img_url']
    upsert_locations(records)

    assert [images.photo_key(params['id']) for params in executed] == keys


# --- caching behaviour -----------------------------------------------------

def test_an_existing_object_is_not_refetched(monkeypatch):
    """Storage *is* the cache. Google's CDN blocks and rate-limits repeat
    requests, and there is no local disk on the free-plan container to cache to."""
    calls = stub_storage(monkeypatch, exists=True)

    urls = images.cache_images([record()])

    assert calls['fetched'] == []
    assert calls['uploads'] == []
    assert urls == [f"https://storage/{calls['exists'][0]}"]


def test_a_missing_object_is_fetched_and_uploaded(monkeypatch):
    calls = stub_storage(monkeypatch, exists=False)

    images.cache_images([record(img_url='https://g/photo')])

    assert calls['fetched'] == ['https://g/photo']
    key, content, content_type = calls['uploads'][0]
    assert key == calls['exists'][0]
    assert content == b'\xff\xd8jpeg'
    assert content_type == 'image/jpeg'


def test_an_empty_photo_url_maps_straight_through(monkeypatch):
    """The output has to stay positionally aligned with `records` - app/main.py
    zips the two together to assign img_url."""
    calls = stub_storage(monkeypatch)

    urls = images.cache_images([
        record(img_url=''),
        record(img_url='https://g/photo'),
        record(img_url=''),
    ])

    assert len(urls) == 3
    assert urls[0] == '' and urls[2] == ''
    assert urls[1].startswith('https://storage/')
    assert calls['fetched'] == ['https://g/photo']


def test_content_type_drops_any_charset_parameter(monkeypatch):
    calls = stub_storage(monkeypatch)
    monkeypatch.setattr(requests, 'get', lambda url, timeout: Response(
        headers={'Content-Type': 'image/jpeg; charset=utf-8'}))

    images.cache_images([record()])

    assert calls['uploads'][0][2] == 'image/jpeg'


def test_content_type_falls_back_when_the_header_is_absent(monkeypatch):
    calls = stub_storage(monkeypatch)
    monkeypatch.setattr(requests, 'get', lambda url, timeout: Response(headers={}))

    images.cache_images([record()])

    assert calls['uploads'][0][2] == 'application/octet-stream'
