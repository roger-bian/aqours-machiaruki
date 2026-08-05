"""Tests for app/storage.py, the Supabase Storage client.

Two branches here encode quirks of the live API that are not documented
anywhere obvious. `download_object`'s 400-means-404, which the bootstrap path
(first ever run, no baseline KML yet) depends on. And `list_object_keys`'
relative names and null-id folder entries - getting either wrong returns a key
set that silently never matches, whose only symptom is re-downloading every
photo from a CDN that rate-limits repeats.
"""
import pytest
import requests

from app import storage


class Response:
    def __init__(self, status_code, content=b'', payload=None):
        self.status_code = status_code
        self.content = content
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError('not JSON')
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


# --- listing ---------------------------------------------------------------

def stub_list(monkeypatch, pages):
    """Serve `pages` (each a list of entries) to successive POSTs. Returns the
    request bodies, so the paging arithmetic is assertable."""
    bodies = []

    def fake_post(url, headers, json, timeout):
        bodies.append(json)
        page = pages[len(bodies) - 1] if len(bodies) <= len(pages) else []
        return Response(200, payload=page)

    monkeypatch.setattr(requests, 'post', fake_post)
    return bodies


def test_list_rebuilds_the_full_key_from_a_relative_name(monkeypatch):
    """Storage returns `name` relative to the prefix - "1", not "locations/1".
    Using it as-is yields a set that matches no photo_key(), so every run
    re-fetches all 136 photos from Google and never errors."""
    stub_list(monkeypatch, [[{'name': '1', 'id': 'a'}, {'name': '10', 'id': 'b'}]])

    assert storage.list_object_keys('locations') == {'locations/1', 'locations/10'}


def test_list_drops_pseudo_folder_entries(monkeypatch):
    """Folders are listed beside real objects and are distinguishable only by a
    null id. One would otherwise become a key no object has."""
    stub_list(monkeypatch, [[
        {'name': 'sub', 'id': None},
        {'name': '1', 'id': 'a'},
    ]])

    assert storage.list_object_keys('locations') == {'locations/1'}


def test_list_pages_until_a_page_comes_back_empty(monkeypatch):
    """Stopping on a *short* page would be the silent-truncation bug: the
    server's real cap is unknown, so a full-looking page is not proof of more
    and a short one is not proof of the end. Offset advances by what arrived."""
    pages = [
        [{'name': str(i), 'id': str(i)} for i in range(1000)],
        [{'name': str(i), 'id': str(i)} for i in range(1000, 1036)],
        [],
    ]
    bodies = stub_list(monkeypatch, pages)

    keys = storage.list_object_keys('locations')

    assert len(keys) == 1036
    assert [b['offset'] for b in bodies] == [0, 1000, 1036]
    assert {b['prefix'] for b in bodies} == {'locations'}
    assert {b['limit'] for b in bodies} == {storage.LIST_PAGE_SIZE}


def test_list_raises_rather_than_reporting_an_empty_bucket(monkeypatch):
    """An empty set means "nothing is cached", which triggers a full re-download
    from a CDN that blocks repeats. A permissions or transport failure must not
    be able to masquerade as that."""
    monkeypatch.setattr(requests, 'post', lambda *a, **k: Response(403))
    with pytest.raises(requests.HTTPError):
        storage.list_object_keys('locations')


# --- download / upload -----------------------------------------------------

def test_download_returns_the_bytes(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: Response(200, b'<kml/>'))
    assert storage.download_object('_pipeline/baseline.kml') == b'<kml/>'


def test_download_treats_404_as_absent(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: Response(404))
    assert storage.download_object('_pipeline/baseline.kml') is None


def test_download_treats_a_400_not_found_body_as_absent(monkeypatch):
    """Supabase Storage answers a missing object with HTTP 400 and puts the real
    status in the body. A plain status_code == 404 check never fires, so
    raise_for_status() used to blow up on the ordinary "no baseline yet" case."""
    body = {'statusCode': '404', 'error': 'not_found', 'message': 'Object not found'}
    monkeypatch.setattr(requests, 'get', lambda *a, **k: Response(400, payload=body))
    assert storage.download_object('_pipeline/baseline.kml') is None


def test_download_raises_on_a_400_that_is_not_a_missing_object(monkeypatch):
    """A malformed request or a permissions problem must not be mistaken for an
    empty bucket - that would silently reset the validation baseline."""
    body = {'statusCode': '400', 'error': 'InvalidRequest'}
    monkeypatch.setattr(requests, 'get', lambda *a, **k: Response(400, payload=body))
    with pytest.raises(requests.HTTPError):
        storage.download_object('_pipeline/baseline.kml')


def test_download_raises_on_a_400_with_an_unparsable_body(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: Response(400, b'<html>'))
    with pytest.raises(requests.HTTPError):
        storage.download_object('_pipeline/baseline.kml')


def test_upload_upserts_and_returns_the_public_url(monkeypatch):
    calls = {}

    def fake_post(url, headers, data, timeout):
        calls.update(url=url, headers=headers, data=data, timeout=timeout)
        return Response(200)

    monkeypatch.setattr(requests, 'post', fake_post)

    result = storage.upload_object('deadbeef', b'\xff\xd8jpeg', 'image/jpeg')

    assert result == storage.public_url('deadbeef')
    # x-upsert is what makes a re-upload of the same key idempotent rather than
    # a 409, which the baseline KML relies on every single run
    assert calls['headers']['x-upsert'] == 'true'
    assert calls['headers']['Content-Type'] == 'image/jpeg'
    assert calls['headers']['apikey'] == storage.SUPABASE_SECRET_KEY
    assert calls['data'] == b'\xff\xd8jpeg'
    assert calls['timeout'] == storage.TIMEOUT


def test_upload_raises_on_failure(monkeypatch):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: Response(403))
    with pytest.raises(requests.HTTPError):
        storage.upload_object('deadbeef', b'x', 'image/jpeg')


def test_public_url_points_at_the_public_object_route():
    """The bucket is public, which is what makes this directly usable as an
    <img src> in the frontend - the img_url column stores exactly this."""
    assert storage.public_url('deadbeef') == (
        f'{storage.SUPABASE_URL}/storage/v1/object/public/'
        f'{storage.SUPABASE_BUCKET}/deadbeef'
    )
