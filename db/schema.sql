-- Schema for the local Postgres + standalone PostgREST setup.
-- Mirrors db/supabase_schema.sql: web_anon here is granted plain SELECT
-- (via PostgREST's db-anon-role), whereas Supabase's cloud Postgres uses
-- RLS policies instead, since RLS is enforced by default there.

CREATE TABLE IF NOT EXISTS locations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    member TEXT,
    address TEXT,
    hours TEXT,
    holidays TEXT,
    img_url TEXT,
    -- collection state, toggled from the frontend directly (not touched by
    -- the pipeline's upsert once a row exists - see pipeline/app/db.py)
    stamp BOOLEAN NOT NULL DEFAULT false,
    badge BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, lat, lon)
);

GRANT USAGE ON SCHEMA public TO web_anon;
GRANT SELECT ON locations TO web_anon;
-- column-scoped: the frontend can flip stamp/badge but can't rename a
-- location, move its coordinates, or change its photo
GRANT UPDATE (stamp, badge) ON locations TO web_anon;
