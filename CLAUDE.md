# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Numazu (沼津) "machiaruki" stamp-rally map: Love Live! Sunshine!! character
stamp locations pulled from a public Google My Maps KML export. Three
separate pieces:

1. **`web/`** — a static React + Vite + Leaflet frontend. Renders numbered,
   color-coded markers (color reflects collection progress), a tap-to-open
   centered detail panel (photo, member, address, hours, holidays, スタンプ/
   缶バッジ checkboxes), and a top-right filter panel. Reads location data
   directly from Supabase's REST API (PostgREST) — no KML parsing or data
   pipeline logic lives in the frontend.
2. **`pipeline/`** — a FastAPI service that owns the entire data pipeline
   (download KML → clean/parse → download photos → upsert into Postgres,
   uploading photos to Supabase Storage). Runs only when
   `POST /pipeline/run` is called.
3. **Supabase** (Postgres + Storage) — the `locations` table (schema in
   `db/supabase_schema.sql`) and the photo bucket.
4. **Auth0** — personal app restricted to a small set of designated emails
   (via Google login only). Auth0 authenticates; Supabase trusts that Auth0
   tenant directly as a **Third-Party Auth** provider (Dashboard >
   Authentication > Third-Party Auth) so RLS evaluates the real Auth0 ID
   token, not a static key. `pipeline/` independently verifies the same ID
   token against Auth0's JWKS for its own `/pipeline/run` endpoint. See
   "Auth (Auth0 + Supabase)" below for the full wiring.

`db/` and `postgrest/` also contain a **local** Postgres + standalone
PostgREST setup (no Docker/Supabase CLI needed) for developing against a
local DB before pointing at Supabase — see `db/schema.sql` vs
`db/supabase_schema.sql` (the latter adds RLS policies Supabase's PostgREST
layer expects; the local one uses plain `GRANT`s instead).

## Environment & commands

- **`pipeline/`**: pyenv-managed virtualenv named `aqours` (see
  `.python-version`), Python 3.10. `pip install -r pipeline/requirements.txt`.
  GDAL requires the native library first (`sudo apt-get install libgdal-dev
  gdal-bin`); the pinned `GDAL==` version must match `gdal-config --version`.
  Run: `cd pipeline && uvicorn app.main:app --port 8000`. Trigger the
  pipeline: needs a valid Auth0 ID token now (see "Auth" below) —
  `curl -X POST http://localhost:8000/pipeline/run -H "Authorization: Bearer <token>"`.
  Credentials (Supabase pooler connection string, secret key, bucket name,
  plus `AUTH0_DOMAIN`/`AUTH0_CLIENT_ID`) live in `pipeline/.env` (gitignored)
  — see README.md for the exact keys.
- **`web/`**: `cd web && npm install && npm run dev` (Vite dev server,
  default port 5173+). `npm run build` for a static production build.
  Credentials (Supabase project URL, publishable key, plus
  `VITE_AUTH0_DOMAIN`/`VITE_AUTH0_CLIENT_ID`/`VITE_PIPELINE_API_BASE`) live
  in `web/.env.local` (gitignored).
- No test suite or linter beyond `tsc`/`oxlint` defaults in `web/`.
- `pipeline/Dockerfile` + root `render.yaml` deploy `pipeline/` to Render
  (Docker runtime, free plan). The container is fully stateless — no
  volume/persistent disk is configured or needed, since the pipeline keeps
  everything that must survive a restart in Supabase (see "Data pipeline"
  below) rather than on local disk. `render.yaml`'s `envVars` are declared
  with `sync: false` (values entered once in the Render dashboard when the
  Blueprint is first connected, not stored in git).
- `nb/nb.ipynb` is a scratch notebook of early data-exploration work. Not
  run as part of anything and may be out of sync — reference only.

## Development workflow

- Start `pipeline/` (`uvicorn app.main:app --port 8000`) and `web/`
  (`npm run dev`) in the background and open the Vite dev URL in the
  browser via the Claude in Chrome extension. Leave both running for the
  rest of the session.
- After any pipeline change, you generally don't need to re-trigger
  `POST /pipeline/run` unless you changed KML-parsing/upsert logic itself —
  the frontend reads from Supabase directly, not from the pipeline process.
- After any frontend change, verify via the Claude in Chrome extension
  (click markers, toggle checkboxes, check the console/network tabs) —
  Vite's HMR means most changes apply without a manual reload, but changes
  to `.env.local` require restarting the dev server.
- **Automated clicks on the Leaflet map are flaky.** A simulated
  `left_click` on a marker sometimes registers as a no-op (Leaflet's hit
  target for a `divIcon` marker is small); retry once or twice before
  assuming a real bug. For deterministic testing of state/logic (not the
  actual click gesture), driving a `<input type="checkbox">` via
  `element.click()` in `javascript_tool` is more reliable than simulated
  mouse coordinates — but note native checkbox DOM state can flip
  synchronously before React's controlled-component re-render catches up,
  so read state back after a short `wait`, not in the same script.

## Data pipeline (`pipeline/`)

1. **`app/kml.py`**: `fetch_kml()` downloads the KML export fresh on every
   call. `os.environ['OGR_SKIP'] = 'LIBKML'` is set **at the top of this
   file, before importing `geotable`/`osgeo`** — this forces GDAL's
   built-in KML driver instead of `LIBKML` (which system `libgdal-dev`
   installs and GDAL otherwise prefers). Load-bearing: `geotable`
   hardcodes a drop-list that deletes the lowercase `description` field
   LIBKML produces; the built-in driver instead exposes it capitalized
   (`Description`), which survives and is what `description.py` expects.
   Removing this line silently breaks image/address/hours/member parsing
   with no error.
2. **`app/description.py`**: `parse_description()` parses each
   placemark's `Description` HTML field (an `<img>` tag +
   `メンバー／`/`住所／`/`営業時間／`/`定休日／` labels in a CDATA blob).
   Fields are located **by string position**, not assumed adjacent to
   fixed neighbors — some entries omit the member or hours label entirely.
   Missing fields degrade to empty string/`'なし'` rather than raising. If
   you touch this parsing, re-check against entries missing labels, not
   just the common case.
3. **`app/images.py`**: `cache_images()` hashes each photo URL (SHA1) and
   uses that digest as the object's key in the Supabase Storage bucket
   (`app/storage.py`) — `object_exists()` is checked first, and the actual
   photo is only fetched from Google's `mymaps.usercontent.google.com` CDN
   (which blocks/rate-limits repeat fetches) on a miss, then uploaded via
   `upload_object()` (`x-upsert: true`). Storage itself *is* the dedupe
   cache — deliberately no local disk involved, since the container has no
   persistent disk on Render's free plan and a restart/redeploy would
   otherwise silently lose it. The frontend reads the `img_url` column
   (the Storage public URL), not any local path.
4. **`app/validation.py`**: `validate_structure()` checks a freshly
   downloaded KML against the *previous* successful run's KML (the
   "accepted structure" baseline) before any DB write is attempted —
   required columns present, every placemark has a name and Point
   geometry, placemark count hasn't collapsed past `MIN_COUNT_RATIO` of
   baseline, and address/image extraction hasn't broken past
   `MAX_EMPTY_ADDRESS_RATIO`/`MAX_EMPTY_IMG_RATIO`. Raises
   `PipelineValidationError` on deviation; `app/main.py` reports this as
   HTTP 422 and discards the download without touching the DB or the
   baseline. On the very first run ever (no baseline yet), the relative
   count-drop check is skipped but every other check still applies.
5. **`app/db.py`**: `upsert_locations()` upserts on the natural key
   `(name, lat, lon)`. Deliberately never touches the `stamp`/`badge`
   columns — not in the `INSERT` column list (new rows get the column
   defaults, both `false`), not in the `ON CONFLICT DO UPDATE SET` clause
   (existing rows keep whatever collection state they have). The pipeline
   owns everything about a location except collection state, which only
   the frontend writes — don't add `stamp`/`badge` to this query.
6. **`app/main.py`** / **`app/pipeline_state.py`**: `POST /pipeline/run`
   requires a valid Auth0 ID token (`app/auth.py`'s `verify_auth0_token`
   dependency — see "Auth" below), then does a fast, lock-protected
   check-and-kickoff and returns almost immediately —
   `{'status': 'started'}` or `{'status': 'already_running'}` — rather
   than blocking for the full run. The actual work
   (`_execute_pipeline_run`, same KML fetch/validate/cache/upsert logic as
   before) runs afterward via FastAPI's `BackgroundTasks`.
   `pipeline_state` holds the shared in-memory `running`/`last_result`/
   `last_error` state behind a `threading.Lock` (atomic check-and-set
   across FastAPI's thread-pool-executed handlers) — deliberately not
   persisted anywhere, so a process restart mid-run self-heals back to
   "not running" rather than getting stuck. `GET /pipeline/status`
   exposes that state for polling. A rejected or failed run still leaves
   the DB/baseline untouched exactly as before — only *when* the pipeline
   itself runs and reports its result changed, not the validation/rollback
   semantics. The baseline KML used by `validate_structure()` is itself
   stored in Supabase Storage (`BASELINE_KML_KEY = '_pipeline/baseline.kml'`,
   same bucket as photos) rather than on local disk. Local temp files
   (`tempfile`) are used only as scratch space to let `geotable.load()`
   parse KML bytes fetched from Storage/Google; nothing on local disk
   needs to persist across requests.

## Frontend (`web/src`)

- **`data/types.ts`**: the `Location` type mirrors the Postgres row
  exactly (including `stamp`/`badge`) — PostgREST returns all columns by
  default, so there's no separate mapping/parsing layer.
- **`data/supabaseRest.ts`**: shared `API_BASE`/`authHeaders()` used by
  both `useLocations` (GET) and `useToggleCollected` (PATCH). Swapping
  Supabase projects is a two-env-var change here, not a code change.
- **`data/markerColors.ts`**: `colorFor()` (blue/orange/green by how many
  of stamp+badge are collected) and `matchesFilters()` (OR semantics
  across the two "not yet collected" filters) both operate directly on a
  `Location`'s `stamp`/`badge` fields — no separate state-map/lookup layer.
- **`hooks/useLocations.ts`**: fetches once on mount; exposes `setLocations`
  so `useToggleCollected` can apply optimistic updates in place.
- **`hooks/useToggleCollected.ts`**: toggling a checkbox optimistically
  updates local state, `PATCH`es Supabase directly, and rolls back on
  failure. Also tracks in-flight `(id, field)` pairs (guarded via a `ref`,
  not just `state`, to avoid a same-tick race) so a rapid double-click on
  the same checkbox can't fire overlapping requests — `DetailPanel` disables
  and shows a spinner on a checkbox while its own write is pending.
- **`map/MapView.tsx`** / **`map/markerIcon.ts`**: Leaflet markers use
  `L.divIcon` (colored circle + number), memoized on `[color, number]`.
  No Leaflet `Popup` is used anywhere — `DetailPanel` is a plain
  fixed-position React div, deliberately centered in the viewport rather
  than anchored to the tapped marker (mobile-friendly, no hover on touch).
- **`panel/Backdrop.tsx`**: a dimmed full-screen div rendered only while
  the panel is open; tapping it (map or otherwise) closes the panel.
  Needed because marker clicks bubble to Leaflet's own map click handler
  by default — without this, a marker tap would open then immediately
  close the panel on the same tap.
- **`hooks/useUserLocation.ts`**: browser Geolocation API
  (`getCurrentPosition`, one-shot, not `watchPosition`). Denied/unsupported
  → no error, just no current-location marker.
- Leaflet's built-in zoom control defaults to the top-left corner — the
  filter panel is positioned top-right (`FilterPanel.tsx`) specifically to
  avoid overlapping it.

## Auth (Auth0 + Supabase)

Personal app restricted to a small set of designated emails — the goal is
that only those emails can ever read/write the data, enforced at the data
layer, not just hidden behind a client-side gate. The actual addresses are
kept out of this repo: `pipeline/app/auth.py` reads them from the
`ALLOWED_EMAILS` env var (comma-separated, `pipeline/.env` locally /
`sync: false` in `render.yaml`), and the Auth0 Action (dashboard-only, not
in this repo) enforces the same allowlist independently.

- **Auth0** authenticates via Google login (`google-oauth2` connection). An
  Auth0 Action (`onExecutePostLogin`, Auth0 dashboard, not in this repo)
  denies login outright to anyone outside the designated emails, and stamps
  `role: 'authenticated'` onto the **ID token** specifically (Auth0
  silently strips unnamespaced custom claims from *access* tokens — this
  is why the ID token, not the access token, is what gets passed around
  everywhere in this app).
- **Supabase** is configured as a Third-Party Auth provider trusting that
  Auth0 tenant directly (Dashboard > Authentication > Third-Party Auth,
  external to this repo) — PostgREST verifies the Auth0 ID token against
  Auth0's JWKS itself and assigns the `authenticated` Postgres role from
  its `role` claim. `db/supabase_schema.sql`'s RLS policies and grants are
  `TO authenticated` only — `anon` (unauthenticated) gets nothing at all,
  a deliberate change from the old fully-permissive `anon` model.
- **`pipeline/app/auth.py`**: independently verifies the same Auth0 ID
  token for `POST /pipeline/run` (`PyJWKClient` against Auth0's JWKS,
  checking signature/issuer/audience/email) — this is separate from and
  unrelated to Supabase's Third-Party Auth trust relationship; the two
  systems just happen to trust the same Auth0 tenant. Deliberately **not**
  a static shared secret: the frontend's "データ更新" button calls this
  endpoint directly from the browser, and anything baked into the Vite
  bundle (`VITE_*` vars) is effectively public once the page loads.
- `web/`'s `AUTH0_DOMAIN`/`AUTH0_CLIENT_ID`-equivalent env vars
  (`VITE_AUTH0_DOMAIN`/`VITE_AUTH0_CLIENT_ID`) and `pipeline/`'s
  (`AUTH0_DOMAIN`/`AUTH0_CLIENT_ID`) are **not secrets** — Auth0
  domain/client ID are meant to be public in an SPA bundle — so they're
  plain `value:` entries in `render.yaml`, not `sync: false`.
- `useRefreshTokens` + `cacheLocation: 'localstorage'` (in `main.tsx`'s
  `Auth0Provider`) avoid Auth0's legacy iframe-based silent-auth, which
  third-party-cookie blocking (Safari/Chrome) increasingly breaks — matters
  concretely here since the app is used in real walking-around-Numazu
  phone sessions, not just quick desktop visits.
- `pipeline/`'s CORS (`app/main.py`) is scoped to the real frontend
  origin(s), not `allow_origins=['*']` — now that real cross-origin
  requests carry an `Authorization` header, a wildcard origin isn't
  appropriate.

## Supabase-specific notes

- API key naming: Supabase's dashboard calls the `anon` key the
  **publishable key**, and the `service_role` key the **secret key**.
  `pipeline/` uses the secret key (Storage uploads); `web/` uses the
  publishable key only for the `apikey` header now (routing, not identity —
  see "Auth" above for what actually gates access).
- The local Postgres setup (`db/schema.sql`) still skips RLS entirely
  (plain `GRANT`s to `web_anon`) and is unaffected by any of the above —
  it's dev-only scaffolding, never deployed, no Auth0 involved.
