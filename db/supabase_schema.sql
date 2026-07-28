-- Supabase variant of db/schema.sql. Supabase's hosted PostgREST layer
-- authenticates unauthenticated requests as the built-in `anon` role (not
-- our local `web_anon`), and its dashboard linter expects RLS enabled with
-- an explicit policy rather than a bare GRANT for anything public-readable.

CREATE TABLE IF NOT EXISTS locations (
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
    img_url TEXT,
    -- collection state, toggled from the frontend directly (not touched by
    -- the pipeline's upsert once a row exists - see pipeline/app/db.py)
    stamp BOOLEAN NOT NULL DEFAULT false,
    badge BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, lat, lon)
);

-- migration path for databases created before hours_json existed (the
-- CREATE TABLE above is IF NOT EXISTS, so it is a no-op on those). Safe to
-- run on the live Supabase project; the existing SELECT grant already covers
-- the new column, and GRANT UPDATE stays scoped to (stamp, badge).
ALTER TABLE locations ADD COLUMN IF NOT EXISTS hours_json JSONB;

ALTER TABLE locations ENABLE ROW LEVEL SECURITY;

-- Personal single-user app: Supabase is configured as a Third-Party Auth
-- provider trusting an Auth0 tenant directly (Dashboard > Authentication >
-- Third-Party Auth), and an Auth0 Action denies login to anyone but the
-- owner's Google account - so `authenticated` here means "is the owner",
-- not "is any signed-up user". `anon` (unauthenticated) gets nothing.
CREATE POLICY "Authenticated read access" ON locations
    FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Authenticated update collection state" ON locations
    FOR UPDATE
    TO authenticated
    USING (true)
    WITH CHECK (true);

GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT ON locations TO authenticated;
-- column-scoped: the frontend can flip stamp/badge but can't rename a
-- location, move its coordinates, or change its photo
GRANT UPDATE (stamp, badge) ON locations TO authenticated;
