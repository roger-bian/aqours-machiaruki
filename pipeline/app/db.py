import os

import psycopg2
from psycopg2.extras import Json, execute_values

DATABASE_URL = os.environ.get(
    'PIPELINE_DATABASE_URL',
    'postgresql://pipeline:pipeline_local_dev@localhost:5432/machiaruki',
)

# One statement for the whole batch. execute_values splits this on the single
# `%s` and pastes a mogrified copy of VALUES_TEMPLATE per row into the gap, so
# the two constants are halves of one statement - anything asserted about "the
# SQL" has to look at both.
#
# Every %(name)s must stay out of *this* half: psycopg2's _split_sql regex-
# splits on (%.) and raises ValueError('unsupported format character') on a
# leftover %(id)s, and ('more than one %s placeholder') on a second %s. A crash
# at the first upsert, not a style point.
UPSERT_SQL = """
    INSERT INTO locations (id, name, lat, lon, member, address, hours, holidays, hours_json, display_json, img_url, updated_at)
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        lat = EXCLUDED.lat,
        lon = EXCLUDED.lon,
        member = EXCLUDED.member,
        address = EXCLUDED.address,
        hours = EXCLUDED.hours,
        holidays = EXCLUDED.holidays,
        hours_json = EXCLUDED.hours_json,
        display_json = EXCLUDED.display_json,
        img_url = EXCLUDED.img_url,
        updated_at = now()
    RETURNING (xmax = 0) AS inserted
"""

VALUES_TEMPLATE = (
    '(%(id)s, %(name)s, %(lat)s, %(lon)s, %(member)s, %(address)s,'
    ' %(hours)s, %(holidays)s, %(hours_json)s, %(display_json)s,'
    ' %(img_url)s, now())'
)

# 136 locations fit in one round trip; psycopg2's default of 100 would quietly
# make it two. Past this, execute_values issues several statements on the same
# cursor inside the same transaction - still atomic, still one RETURNING row
# per input row, just more round trips.
UPSERT_PAGE_SIZE = 1000


def upsert_locations(records):
    """Upsert records keyed on `id`, the placemark's 1-based position in the
    KML - which is the stamp number rendered on the marker, so it is data, not
    a surrogate key. Returns (inserted_count, updated_count).

    The id comes from the caller's list order, never off the record, so
    `records` must arrive in KML order and be the complete set. Supplying it
    explicitly also keeps the id sequence out of it: ON CONFLICT DO UPDATE
    evaluates column defaults before detecting the conflict, so a nextval()
    default burns a value on every row it merely updates.

    `name`/`lat`/`lon` are in DO UPDATE SET - the row at position N has to
    follow the KML if its text changes. `stamp`/`badge` never are, and are not
    in the INSERT column list either: collection state is written only by the
    frontend, and a refresh must leave it exactly as the user left it.

    One statement for the whole batch, not one per row: 136 sequential
    execute+fetchone round trips at ~126ms each was ~17s of every run. Only the
    True/False counts are read off RETURNING, never a row-to-id mapping - so
    nothing depends on the returned rows arriving in input order, which
    Postgres does not promise (and psycopg2 only orders whole pages). What is
    guaranteed and load-bearing: ON CONFLICT DO UPDATE with no WHERE yields
    exactly one result row per input row. Don't swap the counting for
    cur.rowcount - execute_values explicitly does not aggregate it.

    A batch also makes a duplicate id a hard 21000 cardinality_violation
    ("cannot affect row a second time") where the per-row loop silently applied
    both writes. Unconstructible here because the id comes from enumerate(),
    never off the record - which is what test_position_wins_over_any_id_on_the_record
    now guards.
    """
    rows = [
        # Json() adapts the dicts for the jsonb columns; callers pass plain
        # dicts and never have to think about serialization. A fresh dict per
        # record, never an in-place edit - app/main.py counts `unverified` off
        # these same records after the upsert returns.
        {**record,
         'id': position,
         'hours_json': Json(record['hours_json']),
         'display_json': Json(record['display_json'])}
        for position, record in enumerate(records, start=1)
    ]
    # not `with psycopg2.connect(...)`: that commits/rolls back on exit but
    # never closes, leaking a connection per run against Supabase's pooler
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            returned = execute_values(cur, UPSERT_SQL, rows,
                                      template=VALUES_TEMPLATE,
                                      page_size=UPSERT_PAGE_SIZE, fetch=True)
        # the only commit now - an early return added inside this try would
        # roll back silently at close() and still report success
        conn.commit()
    finally:
        # close() rolls back anything uncommitted, so the failure path needs no
        # explicit rollback
        conn.close()
    inserted = sum(1 for (was_inserted,) in returned if was_inserted)
    return inserted, len(returned) - inserted
