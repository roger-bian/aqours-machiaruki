import os

import psycopg2
from psycopg2.extras import Json

DATABASE_URL = os.environ.get(
    'PIPELINE_DATABASE_URL',
    'postgresql://pipeline:pipeline_local_dev@localhost:5432/machiaruki',
)

UPSERT_SQL = """
    INSERT INTO locations (id, name, lat, lon, member, address, hours, holidays, hours_json, display_json, img_url, updated_at)
    VALUES (%(id)s, %(name)s, %(lat)s, %(lon)s, %(member)s, %(address)s, %(hours)s, %(holidays)s, %(hours_json)s, %(display_json)s, %(img_url)s, now())
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
    """
    inserted = 0
    updated = 0
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for position, record in enumerate(records, start=1):
                # Json() adapts the dicts for the jsonb columns; callers pass
                # plain dicts and never have to think about serialization
                cur.execute(UPSERT_SQL, {
                    **record,
                    'id': position,
                    'hours_json': Json(record['hours_json']),
                    'display_json': Json(record['display_json']),
                })
                (was_inserted,) = cur.fetchone()
                if was_inserted:
                    inserted += 1
                else:
                    updated += 1
        conn.commit()
    return inserted, updated
