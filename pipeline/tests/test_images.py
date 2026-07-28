"""Tests for app/images.py.

`cache_images` uses Supabase Storage itself as its dedupe cache, keyed on each
location's natural key. The headline test here is the one that pins *why*: Google
embeds a per-request token in every photo URL, so the URL differs on every KML
fetch. Keying on it produced a cache that never hit, silently re-uploading a
duplicate of every photo on every single run.

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


def test_key_is_the_natural_key_not_the_photo_url(monkeypatch):
    """The regression test for the re-upload-every-run bug. Google re-tokenizes
    the photo URL on every KML fetch, so the same location must still land on the
    same Storage object."""
    calls = stub_storage(monkeypatch)

    first = images.cache_images([record(img_url='https://g/token-A')])
    second = images.cache_images([record(img_url='https://g/token-B')])

    assert first == second
    assert calls['exists'][0] == calls['exists'][1]


def test_distinct_locations_get_distinct_keys(monkeypatch):
    stub_storage(monkeypatch)
    urls = images.cache_images([
        record(name='A', lat=35.1, lon=138.8),
        record(name='B', lat=35.1, lon=138.8),
        record(name='A', lat=35.2, lon=138.8),
    ])
    assert len(set(urls)) == 3


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
        record(name='A', img_url=''),
        record(name='B', img_url='https://g/photo'),
        record(name='C', img_url=''),
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
