"""Tests for app/storage.py, the Supabase Storage client.

`download_object`'s 400-means-404 branch is the interesting one: it encodes a
quirk of the live API that is not documented anywhere obvious, and the bootstrap
path (first ever run, no baseline KML yet) depends on it.
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


def test_object_exists_only_on_200(monkeypatch):
    monkeypatch.setattr(requests, 'head', lambda *a, **k: Response(200))
    assert storage.object_exists('abc') is True
    monkeypatch.setattr(requests, 'head', lambda *a, **k: Response(404))
    assert storage.object_exists('abc') is False


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
