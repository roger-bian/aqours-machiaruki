# lovelive-machiaruki

A Numazu (沼津) "machiaruki" stamp-rally map: Love Live! Sunshine!! character
stamp locations pulled from a public Google My Maps KML export, rendered as
an interactive Leaflet map with a tap-to-open detail panel (photo, member,
address, hours, holidays) and a personal collection tracker (スタンプ/缶バッジ
checkboxes per location).

Each marker carries two independent signals: its **fill** is collection
progress, and its **ring** is whether the place is open right now — green
open, amber closing within two hours, red closed, black permanently closed,
no ring when the source data doesn't say. The two filter checkboxes (`未獲得`
and `営業中のみ`) stack.

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

### Secrets (Infisical)

The three gitignored secret files below (`pipeline/.env`, `web/.env.local`,
`android/keystore.properties`) are mirrored in an Infisical project, one
folder per file under the `prod` environment. If you have access to that
project, pull them straight down instead of filling in values by hand.
`.infisical.json` (committed, holds only the project ID — not a secret)
already links this repo to that project, so the only one-time step is
authenticating your own machine:

```bash
infisical login    # once per machine
infisical export --env=prod --path=/pipeline --format=dotenv --output-file=pipeline/.env
infisical export --env=prod --path=/web --format=dotenv --output-file=web/.env.local
infisical export --env=prod --path=/android --format=dotenv --output-file=android/keystore.properties
```

`android/keystore/release.jks` itself — the actual signing keystore, not
just the passwords/alias in `keystore.properties` — is backed up
separately as a base64 blob under the same `/android` path, since it's
binary and gitignored:

```bash
infisical secrets get keystoreJksBase64 --env=prod --path=/android --plain \
  | base64 -d > android/keystore/release.jks
```

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

> On a project created before the `hours_json` / `display_json` columns
> existed, the `CREATE TABLE IF NOT EXISTS` above is a no-op and won't add
> them. Run the two `ALTER TABLE locations ADD COLUMN IF NOT EXISTS …` lines
> from `db/supabase_schema.sql` in the Supabase SQL Editor instead — don't
> paste the whole file, since `CREATE POLICY` has no `IF NOT EXISTS` and
> will error where the policies already exist. Neither column needs a grant
> or policy change: `GRANT SELECT` is table-wide and `GRANT UPDATE` stays
> scoped to `(stamp, badge)`.

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

Already have a keystore backed up in Infisical (see "Secrets" above)?
Restore it instead of generating a new one — a new keystore signs the
app differently and breaks the fingerprint in `assetlinks.json`.

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

## Business hours

The KML's `営業時間`/`定休日` fields are freeform Japanese —
`10:00～20:00（木曜日は14:00まで）`, `第二・第四火曜日`, `11：00～26：00`,
`不定休`. `pipeline/app/hours.py` turns them into a structured `hours_json`
column (intervals as minutes from midnight) that the frontend evaluates
against the clock in `Asia/Tokyo`.

Parsing is three tiers, keyed by a hash of the raw text: hand-reviewed
entries in `pipeline/app/hours_parsed.json`, then a rule-based fallback.
Tier one exists because the rule tier discards parentheticals as noise
(`（最終入園15:30）`, `(L.O.16:30)`) and so also discards the handful that
carry real hours. Anything falling back to the rule tier is counted and
reported in the データ更新 toast as `N件が未確認`, because that tier fails
confidently rather than loudly.

Roughly 22% of locations can't be fully determined — `不定休` means
"irregular holidays" and the schedule was simply never written down. Those
render honestly (no ring, or a ⚠ caveat) rather than guessing.

```bash
cd pipeline
python -m app.hours                    # review harness: every parse vs its raw text
python tools/gen_hours_overrides.py    # regenerate the override file after a KML change
```

Regenerating preserves existing entries, so hand corrections survive; only
new or upstream-edited entries get a fresh rule-based baseline.

## Tests

```bash
pip install -r pipeline/requirements-dev.txt   # pytest, once
make test                                      # both suites, ~2s
make test-py                                   # pytest for pipeline/ only
make test-web                                  # vitest for web/ only
```

Both halves run **fully offline** — no network, no database. The KML is a
committed fixture trimmed from a real export, and `pipeline/tests/conftest.py`
stubs out database access, since `PIPELINE_DATABASE_URL` normally points at
production.

The weight is on the two places where a bug is a *wrong answer* rather than a
crash: the freeform-Japanese hours parser, and the clock evaluation that turns
its output into a marker's open/closed ring. `pipeline/app/hours_parsed.json`
doubles as a golden corpus for the first — it stores each entry's raw source
text beside its expected parse, so the rule tier is checked against all 125
committed entries at once.

`python -m app.hours` (above) is still the tool for eyeballing new upstream
text, since it fetches the live KML. `make test` is the change gate.

## Notes

- `pipeline`'s upsert (`pipeline/app/db.py`) is keyed on `id`, which is the
  placemark's 1-based position in the KML — that position is the stamp number
  shown on the marker, so it's data, not a surrogate key. It deliberately
  never touches the `stamp`/`badge` columns — those are collection state,
  written only by the frontend (`PATCH` straight to Supabase's REST API),
  never by the pipeline.
- `PIPELINE_DATABASE_URL` normally points at the live Supabase, so a
  locally-run `pipeline/` writes to production — there's no staging DB.
