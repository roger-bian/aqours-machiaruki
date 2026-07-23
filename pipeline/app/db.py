import os

import psycopg2

DATABASE_URL = os.environ.get(
    'PIPELINE_DATABASE_URL',
    'postgresql://pipeline:pipeline_local_dev@localhost:5432/machiaruki',
)

UPSERT_SQL = """
    INSERT INTO locations (name, lat, lon, member, address, hours, holidays, img_url, updated_at)
    VALUES (%(name)s, %(lat)s, %(lon)s, %(member)s, %(address)s, %(hours)s, %(holidays)s, %(img_url)s, now())
    ON CONFLICT (name, lat, lon) DO UPDATE SET
        member = EXCLUDED.member,
        address = EXCLUDED.address,
        hours = EXCLUDED.hours,
        holidays = EXCLUDED.holidays,
        img_url = EXCLUDED.img_url,
        updated_at = now()
    RETURNING (xmax = 0) AS inserted
"""


def upsert_locations(records):
    """Upsert records keyed on the (name, lat, lon) natural key.

    Returns (inserted_count, updated_count). Row `id`s stay stable across
    re-runs for existing (name, lat, lon) combinations, which matters
    because the frontend keys collection state (`stamp`/`badge`) by `id`.
    Deliberately never touches `stamp`/`badge` in the UPDATE SET clause and
    never includes them in the INSERT column list - existing rows keep
    whatever collection state they have, new rows get the column defaults
    (both false), per the frontend/pipeline division of ownership: the
    pipeline owns everything except collection state, which only the
    frontend ever writes.
    """
    inserted = 0
    updated = 0
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for record in records:
                cur.execute(UPSERT_SQL, record)
                (was_inserted,) = cur.fetchone()
                if was_inserted:
                    inserted += 1
                else:
                    updated += 1
        conn.commit()
    return inserted, updated
