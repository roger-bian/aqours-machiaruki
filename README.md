# lovelive-machiaruki

A Numazu (沼津) "machiaruki" stamp-rally map: Love Live! Sunshine!! character
stamp locations pulled from a public Google My Maps KML export, rendered as
an interactive Leaflet map with a tap-to-open detail panel (photo, member,
address, hours, holidays) and a personal collection tracker (スタンプ/缶バッジ
checkboxes per location).

Three separate pieces:

- **`web/`** — React + Vite + Leaflet static frontend. Reads location data
  straight from Supabase's REST API (PostgREST); no KML parsing or data
  pipeline logic lives here at all.
- **`pipeline/`** — a FastAPI service that owns the entire data pipeline
  (download the KML → clean/parse it → download each location's photo →
  upsert into Postgres, uploading photos to Supabase Storage). Runs only
  when its endpoint is triggered, not automatically.
- **Supabase** (Postgres + Storage) — the `locations` table and the image
  bucket. See `db/supabase_schema.sql` for the schema.

`db/` and `postgrest/` also contain a from-scratch **local** Postgres +
standalone PostgREST setup (no Docker/Supabase CLI needed), useful for
developing against a local DB before pointing at the real Supabase project.

## Setup

### `pipeline/`

Uses a pyenv-managed virtualenv named `aqours` (see `.python-version`):

```bash
pyenv install 3.10.20              # if not already installed
pyenv virtualenv 3.10.20 aqours    # if the venv doesn't exist yet
pyenv activate aqours
pip install -r pipeline/requirements.txt
```

The `GDAL` package requires the native GDAL library/headers first
(`sudo apt-get install libgdal-dev gdal-bin`), and the pinned `GDAL==`
version in `pipeline/requirements.txt` must match `gdal-config --version`.

Create `pipeline/.env` (gitignored) with your Supabase project's details:

```
PIPELINE_DATABASE_URL=postgresql://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=<secret key, Settings > API Keys>
SUPABASE_BUCKET=<your bucket name>
AUTH0_DOMAIN=<your-tenant>.<region>.auth0.com
AUTH0_CLIENT_ID=<Auth0 application's Client ID>
```

Use the **connection pooler** string (Settings → Database → Connection
pooling), not the direct connection — the direct one is IPv6-only and often
fails to resolve from local networks.

`AUTH0_DOMAIN`/`AUTH0_CLIENT_ID` come from the Auth0 Single Page
Application you create for `web/` below — the pipeline verifies the same
ID token the frontend uses, independently, for its own `/pipeline/run`
endpoint (see `CLAUDE.md`'s "Auth" section for the full picture).

Run the schema once against your Supabase project (`psql "$PIPELINE_DATABASE_URL" -f db/supabase_schema.sql`),
**and** register Auth0 as a Third-Party Auth provider (Supabase Dashboard →
Authentication → Third-Party Auth), then start the service and trigger a
pipeline run (needs a real Auth0 ID token — easiest to copy one out of the
frontend's network tab after logging in):

```bash
cd pipeline
uvicorn app.main:app --port 8000
curl -X POST http://localhost:8000/pipeline/run -H "Authorization: Bearer <id-token>"
```

### `web/`

```bash
cd web
npm install
```

Create `web/.env.local` (gitignored):

```
VITE_API_BASE=https://<project-ref>.supabase.co/rest/v1
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable key, Settings > API Keys>
VITE_AUTH0_DOMAIN=<your-tenant>.<region>.auth0.com
VITE_AUTH0_CLIENT_ID=<Auth0 application's Client ID>
VITE_PIPELINE_API_BASE=http://localhost:8000
```

Auth0 setup: create a Single Page Application in your Auth0 tenant, enable
the Google social connection, add an `onExecutePostLogin` Action that
denies login to anyone but your own email and sets the `role: authenticated`
custom claim on the ID token, and add `http://localhost:5173` to Allowed
Callback URLs / Logout URLs / Web Origins for local dev.

```bash
npm run dev
```

## Notes

- `pipeline`'s upsert (`pipeline/app/db.py`) is keyed on the natural key
  `(name, lat, lon)` and deliberately never touches the `stamp`/`badge`
  columns — those are collection state, written only by the frontend
  (`PATCH` straight to Supabase's REST API), never by the pipeline.
- `nb/nb.ipynb` is a scratch notebook of early data-exploration work. Not
  run as part of anything and may drift out of sync — reference only.
