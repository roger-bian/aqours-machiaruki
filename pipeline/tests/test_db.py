"""Tests for app/db.py.

Two hard invariants live in UPSERT_SQL, both asserted on the SQL string itself so
they hold without a database.

1. `stamp`/`badge` are collection state, written only by the frontend. If they
   ever appear in the INSERT columns or the DO UPDATE SET clause, a データ更新
   silently wipes the user's collection - the one failure in this repo that
   destroys data the source cannot regenerate.

2. `id` is the placemark's 1-based position in the KML, which is the stamp number
   rendered on the marker. It must be supplied explicitly and be the conflict
   target. Keying on (name, lat, lon) instead once produced phantom markers
   numbered 1411 and 1478: two placemarks carry a literal newline in their
   <name>, a run emitted them space-joined, the natural key missed, and the
   INSERT took a sequence value that ON CONFLICT DO UPDATE had been silently
   burning one-per-placemark-per-run.
"""
import psycopg2
import pytest
from psycopg2.extras import Json

from app.db import UPSERT_SQL, upsert_locations
from app.main import _build_records


class FakeCursor:
    def __init__(self, inserted_flags):
        self._inserted_flags = list(inserted_flags)
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchone(self):
        return (self._inserted_flags.pop(0),)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, inserted_flags):
        self.cursors = []
        self.commits = 0
        self._inserted_flags = inserted_flags

    def cursor(self):
        cursor = FakeCursor(self._inserted_flags)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_connect(monkeypatch):
    """Overrides conftest's no_database guard for this module only."""
    def connect(inserted_flags):
        connection = FakeConnection(inserted_flags)
        monkeypatch.setattr(psycopg2, 'connect', lambda url: connection)
        return connection

    return connect


def record(name='ゲーマーズ沼津店', hours_json=None):
    return {
        'name': name,
        'lat': 35.10157,
        'lon': 138.856807,
        'member': '津島善子',
        'address': '沼津市添地町72青秀ビル1階',
        'hours': '平日 11:00～20:00',
        'holidays': 'なし',
        'hours_json': hours_json if hours_json is not None else {'confidence': 'verified'},
        'img_url': 'https://storage/deadbeef',
    }


# --- the collection-state invariant ---------------------------------------

@pytest.mark.parametrize('column', ['stamp', 'badge'])
def test_upsert_never_mentions_collection_state(column):
    """The pipeline owns every column except these two. A refresh must leave a
    walked-and-collected location exactly as the user left it."""
    assert column not in UPSERT_SQL


def test_upsert_reports_whether_each_row_was_new():
    assert 'RETURNING (xmax = 0) AS inserted' in UPSERT_SQL


# --- the stamp-number invariant -------------------------------------------

def test_upsert_keys_on_id():
    """`id` is the KML position and the number on the marker, so it is the only
    correct conflict target. Keying on (name, lat, lon) makes an upstream rename
    insert a duplicate instead of updating in place."""
    assert 'ON CONFLICT (id) DO UPDATE' in UPSERT_SQL
    assert 'ON CONFLICT (name, lat, lon)' not in UPSERT_SQL


def test_upsert_supplies_id_explicitly():
    """An id that came from the SERIAL default would be a sequence value, not a
    KML position - and ON CONFLICT DO UPDATE advances that sequence on every row
    it merely updates, so the numbers climb without bound."""
    assert 'INSERT INTO locations (id, name' in UPSERT_SQL
    assert '%(id)s' in UPSERT_SQL


@pytest.mark.parametrize('column', ['name', 'lat', 'lon'])
def test_upsert_lets_a_row_follow_the_kml(column):
    """The row at position N has to be able to take N's current text. Leaving
    these out of DO UPDATE SET would freeze a renamed shop at its old name."""
    assert f'{column} = EXCLUDED.{column}' in UPSERT_SQL


def test_ids_are_the_one_based_position_in_the_batch(fake_connect):
    connection = fake_connect([True] * 4)

    upsert_locations([record('A'), record('B'), record('C'), record('D')])

    executed = connection.cursors[0].executed
    assert [params['id'] for _, params in executed] == [1, 2, 3, 4]
    assert [params['name'] for _, params in executed] == ['A', 'B', 'C', 'D']


def test_position_wins_over_any_id_on_the_record(fake_connect):
    """The id is derived from list order, never read off the record - so a stale
    or hand-set id cannot smuggle a wrong stamp number into the table."""
    connection = fake_connect([True, True])
    first, second = record('A'), record('B')
    first['id'] = 999
    second['id'] = 1478

    upsert_locations([first, second])

    executed = connection.cursors[0].executed
    assert [params['id'] for _, params in executed] == [1, 2]


def test_ids_follow_the_kml_placemark_order(fake_connect, placemarks):
    """End to end over the real fixture: KML document order is what assigns the
    stamp numbers, so position N in the KML must become id N in the table."""
    records = _build_records(placemarks)
    for r in records:
        r['img_url'] = 'https://storage/stub'
        del r['_raw_img_url']
    connection = fake_connect([True] * len(records))

    upsert_locations(records)

    executed = connection.cursors[0].executed
    expected = [(i, row['Name']) for i, (_, row) in enumerate(placemarks.iterrows(), start=1)]
    assert [(params['id'], params['name']) for _, params in executed] == expected
    # and specifically that it is 1..N with no gaps, which is what makes the
    # marker labels a contiguous stamp numbering rather than surrogate keys
    assert [params['id'] for _, params in executed] == list(range(1, len(records) + 1))


def test_a_renamed_placemark_updates_in_place(fake_connect):
    """The 1411/1478 regression, reduced: same position, different name text.
    One statement against the existing id, not an insert of a new row."""
    connection = fake_connect([False])

    inserted, updated = upsert_locations([record('海鮮丼と魚河岸定食 かもめ丸')])

    assert (inserted, updated) == (0, 1)
    (_, params), = connection.cursors[0].executed
    assert params['id'] == 1


# --- behaviour -------------------------------------------------------------

def test_counts_inserts_and_updates_separately(fake_connect):
    """These two numbers are what the データ更新 toast reports."""
    connection = fake_connect([True, False, True])

    inserted, updated = upsert_locations([record('A'), record('B'), record('C')])

    assert (inserted, updated) == (2, 1)
    assert connection.commits == 1


def test_every_record_is_executed_once(fake_connect):
    connection = fake_connect([True, True])

    upsert_locations([record('A'), record('B')])

    executed = connection.cursors[0].executed
    assert len(executed) == 2
    assert [params['name'] for _, params in executed] == ['A', 'B']


def test_hours_json_is_adapted_for_the_jsonb_column(fake_connect):
    """Wrapped at execute time so callers hand over a plain dict and never think
    about serialization."""
    connection = fake_connect([True])
    schedule = {'weekly': None, 'confidence': 'auto'}

    upsert_locations([record(hours_json=schedule)])

    _, params = connection.cursors[0].executed[0]
    assert isinstance(params['hours_json'], Json)
    assert params['hours_json'].adapted == schedule


def test_the_caller_s_record_is_not_mutated(fake_connect):
    """app/main.py counts `unverified` off these records after the upsert, so a
    hours_json replaced in place would break that count."""
    fake_connect([True])
    original = record()

    upsert_locations([original])

    assert original['hours_json'] == {'confidence': 'verified'}


def test_an_empty_batch_touches_nothing(fake_connect):
    connection = fake_connect([])
    assert upsert_locations([]) == (0, 0)
    assert connection.cursors[0].executed == []
