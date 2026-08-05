"""Tests for app/db.py.

Two hard invariants live in the upsert SQL, both asserted on the string itself
so they hold without a database. The statement is now split across two
constants - execute_values pastes VALUES_TEMPLATE into UPSERT_SQL's single `%s`
- so anything about the whole statement has to check `UPSERT_SQL +
VALUES_TEMPLATE`, or it silently stops covering half of it.

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

from app import db
from app.db import UPSERT_PAGE_SIZE, UPSERT_SQL, VALUES_TEMPLATE, upsert_locations
from app.main import _build_records


class FakeCursor:
    """Nothing is asserted here - execute_values is faked out, so the cursor
    only has to be a context manager."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self):
        self.cursors = []
        self.commits = 0
        self.closes = 0

    def cursor(self):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.commits += 1

    def close(self):
        self.closes += 1


class FakeDb:
    """Captures the one batched call app/db.py makes.

    Patched at `app.db.execute_values`, not `psycopg2.extras`: db.py imports
    the name into its own namespace, so patching the origin does nothing (the
    trap documented at the top of test_images.py). It is also the only seam
    that still sees the per-row mappings - the real execute_values mogrifies
    them into a single byte string before the cursor ever hears about them.
    """
    def __init__(self, inserted_flags):
        self.connection = FakeConnection()
        self.batches = []
        self._flags = list(inserted_flags)

    def execute_values(self, cur, sql, argslist, template=None, page_size=100,
                       fetch=False):
        rows = list(argslist)
        self.batches.append({'sql': sql, 'rows': rows, 'template': template,
                             'page_size': page_size, 'fetch': fetch})
        returned = [(self._flags.pop(0),) for _ in rows]
        return returned if fetch else None

    @property
    def rows(self):
        """Every mapping handed to execute_values, in batch order."""
        return [row for batch in self.batches for row in batch['rows']]


@pytest.fixture
def fake_db(monkeypatch):
    """Overrides conftest's no_database guard for this module only."""
    def start(inserted_flags):
        fake = FakeDb(inserted_flags)
        monkeypatch.setattr(psycopg2, 'connect', lambda url: fake.connection)
        monkeypatch.setattr(db, 'execute_values', fake.execute_values)
        return fake

    return start


def record(name='ゲーマーズ沼津店', hours_json=None, display_json=None):
    return {
        'name': name,
        'lat': 35.10157,
        'lon': 138.856807,
        'member': '津島善子',
        'address': '沼津市添地町72青秀ビル1階',
        'hours': '平日 11:00～20:00',
        'holidays': 'なし',
        'hours_json': hours_json if hours_json is not None else {'confidence': 'verified'},
        'display_json': display_json if display_json is not None else {
            'name': [name], 'address': ['沼津市添地町72青秀ビル1階'],
            'hours': ['平日 11:00～20:00'], 'holidays': ['なし'],
            'extra': [], 'confidence': 'verified'},
        'img_url': 'https://storage/deadbeef',
    }


# --- the collection-state invariant ---------------------------------------

@pytest.mark.parametrize('column', ['stamp', 'badge'])
def test_upsert_never_mentions_collection_state(column):
    """The pipeline owns every column except these two. A refresh must leave a
    walked-and-collected location exactly as the user left it.

    Both halves: the column list and DO UPDATE SET live in UPSERT_SQL, the
    per-row values in VALUES_TEMPLATE, and this is the one invariant here whose
    failure destroys data the source cannot regenerate."""
    assert column not in UPSERT_SQL + VALUES_TEMPLATE


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
    assert '%(id)s' in VALUES_TEMPLATE
    # and specifically *not* in the other half: psycopg2's _split_sql regex-
    # splits UPSERT_SQL on (%.) and raises on any %( it finds, so a named
    # placeholder left behind there is a crash at the first upsert
    assert '%(id)s' not in UPSERT_SQL


@pytest.mark.parametrize('column',
                         ['name', 'lat', 'lon', 'hours_json', 'display_json'])
def test_upsert_lets_a_row_follow_the_kml(column):
    """The row at position N has to be able to take N's current text. Leaving
    these out of DO UPDATE SET would freeze a renamed shop at its old name -
    or, for display_json, keep every existing row on its first-ever set of
    line breaks no matter how often the override file is regenerated."""
    assert f'{column} = EXCLUDED.{column}' in UPSERT_SQL


def test_ids_are_the_one_based_position_in_the_batch(fake_db):
    fake = fake_db([True] * 4)

    upsert_locations([record('A'), record('B'), record('C'), record('D')])

    assert [row['id'] for row in fake.rows] == [1, 2, 3, 4]
    assert [row['name'] for row in fake.rows] == ['A', 'B', 'C', 'D']


def test_position_wins_over_any_id_on_the_record(fake_db):
    """The id is derived from list order, never read off the record - so a stale
    or hand-set id cannot smuggle a wrong stamp number into the table.

    Load-bearing twice over now the batch is one statement: a repeated id in a
    single VALUES list is a hard 21000 cardinality_violation ("cannot affect row
    a second time"), where the per-row loop merely applied both writes."""
    fake = fake_db([True, True])
    first, second = record('A'), record('B')
    first['id'] = 999
    second['id'] = 1478

    upsert_locations([first, second])

    assert [row['id'] for row in fake.rows] == [1, 2]


def test_ids_follow_the_kml_placemark_order(fake_db, placemarks):
    """End to end over the real fixture: KML document order is what assigns the
    stamp numbers, so position N in the KML must become id N in the table."""
    records = _build_records(placemarks)
    for r in records:
        r['img_url'] = 'https://storage/stub'
        del r['_raw_img_url']
    fake = fake_db([True] * len(records))

    upsert_locations(records)

    expected = [(i, row['Name']) for i, (_, row) in enumerate(placemarks.iterrows(), start=1)]
    assert [(row['id'], row['name']) for row in fake.rows] == expected
    # and specifically that it is 1..N with no gaps, which is what makes the
    # marker labels a contiguous stamp numbering rather than surrogate keys
    assert [row['id'] for row in fake.rows] == list(range(1, len(records) + 1))


def test_a_renamed_placemark_updates_in_place(fake_db):
    """The 1411/1478 regression, reduced: same position, different name text.
    One statement against the existing id, not an insert of a new row."""
    fake = fake_db([False])

    inserted, updated = upsert_locations([record('海鮮丼と魚河岸定食 かもめ丸')])

    assert (inserted, updated) == (0, 1)
    (row,) = fake.rows
    assert row['id'] == 1


# --- behaviour -------------------------------------------------------------

def test_counts_inserts_and_updates_separately(fake_db):
    """These two numbers are what the データ更新 toast reports. They come off
    RETURNING, so the batch has to actually ask for the rows back."""
    fake = fake_db([True, False, True])

    inserted, updated = upsert_locations([record('A'), record('B'), record('C')])

    assert (inserted, updated) == (2, 1)
    assert fake.batches[0]['fetch'] is True
    assert fake.connection.commits == 1
    # `with psycopg2.connect(...)` commits but never closes - one leaked
    # connection per run against Supabase's pooler
    assert fake.connection.closes == 1


def test_the_whole_batch_is_one_statement(fake_db):
    """The regression test for the batching itself: 136 sequential
    execute+fetchone round trips at ~126ms each was ~17s of every run."""
    fake = fake_db([True, True])

    upsert_locations([record('A'), record('B')])

    assert len(fake.batches) == 1
    assert [row['name'] for row in fake.rows] == ['A', 'B']
    # one call is not one statement: execute_values splits an argslist longer
    # than page_size into one statement each. psycopg2's default of 100 would
    # already split the live 136 locations in two, so the constant is the real
    # invariant here, not the call count.
    assert fake.batches[0]['page_size'] == UPSERT_PAGE_SIZE
    assert UPSERT_PAGE_SIZE >= 1000


@pytest.mark.parametrize('column,value', [
    ('hours_json', {'weekly': None, 'confidence': 'auto'}),
    ('display_json', {'name': ['A'], 'extra': [], 'confidence': 'auto'}),
])
def test_a_jsonb_column_is_wrapped_for_the_caller(fake_db, column, value):
    """Wrapped as the batch is built so callers hand over a plain dict and never
    think about serialization."""
    fake = fake_db([True])

    upsert_locations([record(**{column: value})])

    row = fake.rows[0]
    assert isinstance(row[column], Json)
    assert row[column].adapted == value


def test_the_caller_s_record_is_not_mutated(fake_db):
    """app/main.py counts `unverified` off these records after the upsert, so a
    hours_json replaced in place would break that count - which is why the batch
    is built from fresh dicts rather than by editing the records."""
    fake_db([True])
    original = record()

    upsert_locations([original])

    assert original['hours_json'] == {'confidence': 'verified'}


def test_an_empty_batch_touches_nothing(fake_db):
    """The real execute_values never touches the cursor on an empty argslist -
    no mogrify, no execute, no fetchall, just []. So there is no early return to
    write here; the connection does still open, and must still close."""
    fake = fake_db([])
    assert upsert_locations([]) == (0, 0)
    assert fake.rows == []
    assert fake.connection.closes == 1
