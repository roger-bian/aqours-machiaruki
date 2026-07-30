-- Schema for the local Postgres + standalone PostgREST setup.
-- Mirrors db/supabase_schema.sql: web_anon here is granted plain SELECT
-- (via PostgREST's db-anon-role), whereas Supabase's cloud Postgres uses
-- RLS policies instead, since RLS is enforced by default there.

CREATE TABLE IF NOT EXISTS locations (
    -- NOT an arbitrary surrogate key: `id` is the placemark's 1-based position
    -- in the KML, which is the stamp number shown on the marker. The pipeline
    -- always supplies it explicitly (see pipeline/app/db.py), so the SERIAL
    -- default is a fallback that should never fire.
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    member TEXT,
    address TEXT,
    hours TEXT,
    holidays TEXT,
    -- structured schedule parsed from `hours`/`holidays` by
    -- pipeline/app/hours.py; the frontend evaluates it against the clock to
    -- colour each marker's open/closed ring. `hours`/`holidays` remain the
    -- human-readable text shown in the detail panel.
    hours_json JSONB,
    -- pre-broken display lines for name/address/hours/holidays plus the その他
    -- section, from pipeline/app/display.py. The text columns above stay
    -- faithful to the KML: the detail panel renders these, but the address's
    -- Google Maps query needs the unbroken string, and a break is lossy.
    display_json JSONB,
    img_url TEXT,
    -- collection state, toggled from the frontend directly (not touched by
    -- the pipeline's upsert once a row exists - see pipeline/app/db.py)
    stamp BOOLEAN NOT NULL DEFAULT false,
    badge BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- migration path for databases created before hours_json existed (the
-- CREATE TABLE above is IF NOT EXISTS, so it is a no-op on those)
ALTER TABLE locations ADD COLUMN IF NOT EXISTS hours_json JSONB;

GRANT USAGE ON SCHEMA public TO web_anon;
GRANT SELECT ON locations TO web_anon;
-- column-scoped: the frontend can flip stamp/badge but can't rename a
-- location, move its coordinates, or change its photo
GRANT UPDATE (stamp, badge) ON locations TO web_anon;
