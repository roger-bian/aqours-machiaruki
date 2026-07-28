"""Tests for app/validation.py, the gate between a botched upstream KML export
and production data. A rejection here means the download is discarded and both
the database and the accepted-structure baseline are left untouched.

`validate_structure` only needs `.columns`, `len()` and `.iterrows()`, so these
build a plain DataFrame with shapely geometries - no GDAL and no KML fixture.
"""
import pandas
import pytest
from shapely.geometry import LineString, Point

from app.validation import (
    MAX_EMPTY_ADDRESS_RATIO,
    PipelineValidationError,
    validate_structure,
)


def frame(rows):
    return pandas.DataFrame(rows)


def placemark(name='ゲーマーズ沼津店', geometry=None):
    return {
        'Name': name,
        'Description': 'メンバー／津島善子<br>住所／沼津市<br>営業時間／10:00～20:00',
        'geometry_object': geometry if geometry is not None else Point(138.85, 35.10),
    }


def fields(count, address='沼津市', img_url='https://example.com/a.jpg',
           hours='10:00～20:00'):
    return [{'address': address, 'img_url': img_url, 'hours': hours}] * count


def test_accepts_a_well_formed_export():
    validate_structure(frame([placemark()] * 10), 10, fields(10))


def test_accepts_the_first_ever_run():
    """No baseline yet (baseline_count 0) skips only the count-drop check."""
    validate_structure(frame([placemark()] * 3), 0, fields(3))


@pytest.mark.parametrize('column', ['Name', 'Description', 'geometry_object'])
def test_rejects_a_missing_column(column):
    """A missing capitalized `Description` is what happens if GDAL picks the
    LIBKML driver - see app/kml.py's OGR_SKIP."""
    row = placemark()
    del row[column]
    with pytest.raises(PipelineValidationError, match='missing expected columns'):
        validate_structure(frame([row]), 1, fields(1))


def test_rejects_an_empty_export():
    with pytest.raises(PipelineValidationError, match='no placemarks'):
        validate_structure(frame({'Name': [], 'Description': [],
                                  'geometry_object': []}), 10, [])


def test_rejects_a_collapsed_placemark_count():
    """Half the baseline reads as a botched export rather than shops closing."""
    with pytest.raises(PipelineValidationError, match='count dropped too far'):
        validate_structure(frame([placemark()] * 4), 10, fields(4))


def test_accepts_a_count_exactly_at_the_ratio():
    """MIN_COUNT_RATIO is a strict `<`, so exactly half still passes."""
    validate_structure(frame([placemark()] * 5), 10, fields(5))


@pytest.mark.parametrize('name', ['', '   '])
def test_rejects_an_empty_name(name):
    """`name` is part of the upsert's natural key, so a blank one would create a
    junk row rather than update an existing location."""
    with pytest.raises(PipelineValidationError, match='empty Name'):
        validate_structure(frame([placemark(name=name)]), 1, fields(1))


def test_rejects_a_non_point_geometry():
    geometry = LineString([(138.85, 35.10), (138.86, 35.11)])
    with pytest.raises(PipelineValidationError, match='non-point geometry'):
        validate_structure(frame([placemark(geometry=geometry)]), 1, fields(1))


def test_rejects_geometry_without_coordinates():
    class NotAGeometry:
        geom_type = 'Point'

    with pytest.raises(PipelineValidationError, match='non-point geometry'):
        validate_structure(frame([placemark(geometry=NotAGeometry())]), 1, fields(1))


@pytest.mark.parametrize('field,message', [
    ('address', 'missing address'),
    ('img_url', 'missing image'),
    ('hours', 'missing business hours'),
])
def test_rejects_too_many_empty_extractions(field, message):
    """Individually these are legitimate - one hotel has no 営業時間 label - but a
    cluster of them means the Description HTML format itself changed."""
    rows = fields(10)
    rows = [dict(r) for r in rows]
    for row in rows[:2]:
        row[field] = ''
    with pytest.raises(PipelineValidationError, match=message):
        validate_structure(frame([placemark()] * 10), 10, rows)


@pytest.mark.parametrize('field', ['address', 'img_url', 'hours'])
def test_accepts_an_empty_extraction_rate_exactly_at_the_ratio(field):
    """The checks use a strict `>`, so exactly 10% passes - which is what gives
    the single label-less hotel its headroom."""
    rows = [dict(r) for r in fields(10)]
    rows[0][field] = ''
    validate_structure(frame([placemark()] * 10), 10, rows)


def test_ratio_constants_leave_room_for_the_known_gaps():
    """136 locations with exactly one missing 営業時間 label - if these were ever
    tightened to zero, an ordinary run would start failing."""
    assert MAX_EMPTY_ADDRESS_RATIO > 1 / 136
