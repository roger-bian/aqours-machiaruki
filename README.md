# lovelive-machiaruki

A Numazu (沼津) "machiaruki" stamp-rally map: Love Live! Sunshine!! character
stamp locations pulled from a public Google My Maps KML export, rendered as
an interactive Leaflet map with a tap-to-open detail panel (photo, member,
address, hours, holidays) and a personal collection tracker (スタンプ/缶バッジ
checkboxes per location).

Four separate pieces:

- **`web/`** — React + Vite + Leaflet static frontend. Reads location data
  straight from Supabase's REST API (PostgREST); no KML parsing or data
  pipeline logic lives here at all.
- **`pipeline/`** — a FastAPI service that owns the entire data pipeline
  (download the KML → clean/parse it → download each location's photo →
  upsert into Postgres, uploading photos to Supabase Storage). Runs only
  when its endpoint is triggered, not automatically.
- **`android/`** — a personal-sideload-only Android wrapper that opens the
  deployed `web/` site fullscreen via a Trusted Web Activity. Not
  published to Google Play.
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
ALLOWED_EMAILS=<comma-separated emails allowed to trigger the pipeline>
```

Use the **connection pooler** string (Settings → Database → Connection
pooling), not the direct connection — the direct one is IPv6-only and often
fails to resolve from local networks.

`AUTH0_DOMAIN`/`AUTH0_CLIENT_ID` come from the Auth0 Single Page
Application you create for `web/` below — the pipeline verifies the same
ID token the frontend uses, independently, for its own `/pipeline/run`
endpoint (see `CLAUDE.md`'s "Auth" section for the full picture).
`ALLOWED_EMAILS` is required (no default — `pipeline/app/auth.py` raises
on startup if it's unset) and must match the same allowlist enforced
independently by the Auth0 Action that gates login itself.

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

### `android/`

Personal-sideload-only Android wrapper (see `CLAUDE.md` for why it uses a
Trusted Web Activity instead of a `WebView`). Needs a JDK 17 and the
Android SDK command-line tools (`platform-tools`, `platforms;android-34`,
`build-tools;34.0.0`).

Generate a dedicated signing keystore once — don't reuse the
auto-generated debug keystore, since the fingerprint needs to stay stable
across rebuilds:

```bash
keytool -genkeypair -v -keystore android/keystore/release.jks \
  -alias aqoursmachiaruki -keyalg RSA -keysize 2048 -validity 10000
```

Create `android/keystore.properties` (gitignored):

```
storeFile=keystore/release.jks
storePassword=<password you set above>
keyAlias=aqoursmachiaruki
keyPassword=<same password>
```

Create `android/local.properties` (gitignored) pointing at your Android
SDK:

```
sdk.dir=/path/to/android-sdk
```

Get the keystore's SHA-256 fingerprint and put it in
`web/public/.well-known/assetlinks.json`'s `sha256_cert_fingerprints`,
replacing the placeholder there — this is what lets Chrome verify the app
owns the domain and render it fullscreen instead of with a Custom Tab
toolbar:

```bash
keytool -list -v -keystore android/keystore/release.jks -alias aqoursmachiaruki
```

Build and sideload onto a phone with USB debugging enabled:

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Notes

- `pipeline`'s upsert (`pipeline/app/db.py`) is keyed on the natural key
  `(name, lat, lon)` and deliberately never touches the `stamp`/`badge`
  columns — those are collection state, written only by the frontend
  (`PATCH` straight to Supabase's REST API), never by the pipeline.
- `nb/nb.ipynb` is a scratch notebook of early data-exploration work. Not
  run as part of anything and may drift out of sync — reference only.
