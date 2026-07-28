"""Tests for app/db.py.

The column list in UPSERT_SQL carries a hard invariant: `stamp`/`badge` are
collection state, written only by the frontend. If they ever appear in the INSERT
columns or the DO UPDATE SET clause, a データ更新 silently wipes the user's
collection - the one failure in this repo that destroys data the source cannot
regenerate. Those assertions are on the SQL string itself, so they hold without a
database.
"""
import psycopg2
import pytest
from psycopg2.extras import Json

from app.db import UPSERT_SQL, upsert_locations


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


def test_upsert_keys_on_the_natural_key():
    """Row ids have to stay stable across runs, because the frontend keys
    collection state by id - a different conflict target would orphan it."""
    assert 'ON CONFLICT (name, lat, lon)' in UPSERT_SQL


def test_upsert_reports_whether_each_row_was_new():
    assert 'RETURNING (xmax = 0) AS inserted' in UPSERT_SQL


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
