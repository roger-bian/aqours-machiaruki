"""Tests for app/kml.py.

The first two are the point of this file. `OGR_SKIP=LIBKML` in app/kml.py is the
repo's most dangerous single line: remove it and GDAL prefers the LIBKML driver,
which exposes the placemark description in lowercase, which geotable's hardcoded
drop-list deletes - so image/address/hours/member parsing all silently return
empty strings with no error anywhere. These turn that into a failing test.
"""
import os

import pytest
import requests

from app.description import extract_img_url, parse_description
from app.kml import KML_URL, TIMEOUT, fetch_kml, load_placemarks
from app.validation import MAX_EMPTY_HOURS_RATIO


def test_ogr_skip_forces_the_builtin_kml_driver():
    assert os.environ.get('OGR_SKIP') == 'LIBKML'


def test_description_column_is_capitalized(placemarks):
    """geotable deletes a lowercase `description`; the built-in driver's
    capitalized `Description` is what survives and what the parsers expect."""
    assert 'Description' in placemarks.columns
    assert 'description' not in placemarks.columns
    assert placemarks['Description'].str.contains('メンバー／').any()


def test_fixture_parses_end_to_end(placemarks):
    """Keeps the fixture honest: if a trim ever breaks its structure, this fails
    rather than the tests that depend on it quietly passing on empty data."""
    assert len(placemarks) == 12
    for _, row in placemarks.iterrows():
        assert str(row['Name']).strip()
        assert row.geometry_object.geom_type == 'Point'
        assert 34 < row.geometry_object.y < 36
        assert 138 < row.geometry_object.x < 140
        assert extract_img_url(row['Description'])
        assert parse_description(row['Description'])['address']


def test_fixture_covers_the_awkward_cases(placemarks):
    """Each placemark in the fixture is there for a specific reason; assert the
    coverage rather than trusting the comment at the top of the file."""
    parsed = {row['Name']: parse_description(row['Description'])
              for _, row in placemarks.iterrows()}

    assert '平日' in parsed['ゲーマーズ沼津店']['raw_hours']
    assert parsed['三交イン 沼津駅前']['raw_hours'] == ''
    assert '閉店により' in parsed['マルサン書店']['holidays']
    assert '（木曜日は14:00まで）' in parsed['びゅうお']['raw_hours']
    assert parsed['食堂・ひもの販売　あじや']['raw_holidays'] == '第二・第四火曜日'
    assert parsed['マルニ茶業　沼津みなと新鮮館']['raw_holidays'] == '第2･4火曜日'
    assert '24時間' in parsed['セブンイレブン 伊豆・三津シーパラダイス前店']['raw_hours']
    assert parsed['沼津グランドホテル']['raw_hours'] == '年中無休'
    assert parsed['安田屋旅館']['raw_holidays'] == '不定休'
    assert '昼休み' in parsed['伊豆箱根バス']['raw_hours']
    assert 'L.O.' in parsed['千本一']['raw_hours']
    # 休館日／ is not one of FIELD_LABELS, so its text falls inside the 営業時間
    # slice rather than becoming the holidays - which is exactly why this entry
    # needs a hand-written override
    assert parsed['沼津市歴史民俗資料館']['member'] == ''
    assert '休館日' in parsed['沼津市歴史民俗資料館']['raw_hours']
    assert parsed['沼津市歴史民俗資料館']['holidays'] == 'なし'


def test_fixture_has_production_like_extraction_ratios(placemarks):
    """app/validation.py rejects a download when >10% of rows are missing an
    address, image or hours. The fixture has to stay under that or the
    orchestration tests would have to fake the real validator away."""
    fields = [parse_description(row['Description'])
              for _, row in placemarks.iterrows()]
    missing_hours = sum(1 for f in fields if not f['hours'])
    assert missing_hours == 1
    assert missing_hours / len(fields) <= MAX_EMPTY_HOURS_RATIO


def test_fetch_kml_writes_the_response_body(tmp_path, monkeypatch):
    calls = {}

    class Response:
        content = b'<?xml version="1.0"?><kml/>'

        def raise_for_status(self):
            calls['raised'] = False

    def fake_get(url, timeout):
        calls['url'] = url
        calls['timeout'] = timeout
        return Response()

    monkeypatch.setattr(requests, 'get', fake_get)
    target = tmp_path / 'sub' / 'new.kml'

    assert fetch_kml(str(target)) == str(target)
    assert target.read_bytes() == Response.content
    assert calls['url'] == KML_URL
    # a stalled request must not be able to block a run forever
    assert calls['timeout'] == TIMEOUT


def test_fetch_kml_propagates_an_http_error(tmp_path, monkeypatch):
    """A failed download must not leave a truncated file behind for
    load_placemarks to misread."""
    class Response:
        content = b''

        def raise_for_status(self):
            raise requests.HTTPError('503')

    monkeypatch.setattr(requests, 'get', lambda url, timeout: Response())
    target = tmp_path / 'new.kml'

    with pytest.raises(requests.HTTPError):
        fetch_kml(str(target))
    assert not target.exists()
