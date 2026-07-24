# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Numazu (沼津) "machiaruki" stamp-rally map: Love Live! Sunshine!! character
stamp locations pulled from a public Google My Maps KML export. Five
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
3. **`android/`** — a personal-sideload-only Android wrapper (not
   published to Google Play) that opens the deployed `web/` site
   fullscreen via a Trusted Web Activity. See "Android app (`android/`)"
   below.
4. **Supabase** (Postgres + Storage) — the `locations` table (schema in
   `db/supabase_schema.sql`) and the photo bucket.
5. **Auth0** — personal app restricted to a small set of designated emails
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
- **`android/`**: needs a JDK 17 and the Android SDK command-line tools
  (`platform-tools`, `platforms;android-34`, `build-tools;34.0.0`), pointed
  at via `android/local.properties`'s `sdk.dir` (gitignored,
  machine-specific). Build: `cd android && ./gradlew assembleDebug`.
  Sideload onto a phone with USB debugging enabled:
  `adb install -r app/build/outputs/apk/debug/app-debug.apk`. Signing
  keystore credentials live in `android/keystore.properties` (gitignored)
  — see README.md for how to generate one and wire up
  `web/public/.well-known/assetlinks.json` to match.
- No test suite or linter beyond `tsc`/`oxlint` defaults in `web/`.
- Root `render.yaml` defines **two** Render services, both auto-deploying
  on push to the connected branch: `aqours-machiaruki-pipeline`
  (`pipeline/Dockerfile`, Docker runtime, free plan, `buildFilter` scoped
  to `pipeline/**` so it only rebuilds when that path changes) and
  `aqours-machiaruki-web` (`runtime: static`, `rootDir: ./web`, `npm ci &&
  npm run build`, no `buildFilter` — redeploys on every push regardless of
  which paths changed). The pipeline container is fully stateless — no
  volume/persistent disk is configured or needed, since the pipeline keeps
  everything that must survive a restart in Supabase (see "Data pipeline"
  below) rather than on local disk. Both services' `envVars` are declared
  with `sync: false` for secrets (values entered once in the Render
  dashboard when the Blueprint is first connected, not stored in git) or
  a plain `value:` for the non-secret Auth0 domain/client ID (see "Auth"
  below for why those are safe to commit).

## Development workflow

- Only start the `pipeline/` (`uvicorn app.main:app --port 8000`) or
  `web/` (`npm run dev`) dev servers on demand, when actually doing local
  testing — don't start them proactively or leave them running by
  default.
- After any pipeline change, you generally don't need to re-trigger
  `POST /pipeline/run` unless you changed KML-parsing/upsert logic itself —
  the frontend reads from Supabase directly, not from the pipeline process.
- Frontend changes are verified by the user manually unless otherwise
  stated.

## Git commit conventions

- When committing, group the working tree's changes by logical category
  (e.g., one feature/fix per commit) and commit each category separately
  rather than as one large commit.
- Never roll back or discard the current repo state (`git reset`/
  `checkout`/`stash`, etc.) just to reconstruct cleaner, more perfectly
  separated category commits — work forward from whatever is currently in
  the working tree, don't rewrite it to fit the categorization.
- If a file's current uncommitted state belongs to a new category but
  overlaps with a change that would otherwise have been split into an
  earlier category, don't try to divide that file's diff between the two
  commits — the current state and its category take precedence, and the
  earlier category's changes to that file get rolled into this commit
  instead of kept separate.

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
  `authHeaders()` is `async` — it sources the `Authorization` header from a
  live Auth0 ID token via a registered getter (`registerIdTokenGetter()`),
  not a static key; `apikey` still sends the static publishable key
  unchanged (Supabase's gateway needs it for project routing regardless of
  auth method).
- **`auth/AuthGate.tsx`**: wraps the whole app (see `main.tsx`, inside
  `Auth0Provider`). Nothing renders behind it until Auth0 login succeeds
  (`loginWithRedirect` with `connection: 'google-oauth2'`, skipping Auth0's
  account-chooser) — an Auth0 Action server-side denies anyone but the
  owner's email, so this is a real gate, not just a client-side one. Once
  authenticated, its `useEffect` calls `registerIdTokenGetter()` so
  `supabaseRest.ts` can fetch a fresh ID token per request.
- **`panel/RefreshDataButton.tsx`**: the "データ更新" button — calls
  `useAuth0().getIdTokenClaims()` directly (it's inside the same
  `Auth0Provider` tree) and `POST`s the raw ID token to
  `VITE_PIPELINE_API_BASE`'s `/pipeline/run`, which verifies it
  independently (see "Auth" below). That request returns almost
  immediately (`'started'` or `'already_running'` — the backend runs the
  actual pipeline afterward, not inline), so the button's own loading
  state only covers that quick round-trip; a `Toast` then reports
  `'started'` vs `'already_running'`, and a `pollUntilDone()` loop (`GET
  /pipeline/status` every ~3s) picks up the eventual result regardless of
  which one it was — on success it shows a toast and
  `window.location.reload()`s once that toast dismisses, on error it just
  shows the error toast. A mount-time effect does the same single status
  check (no `POST`) so a run left in progress by some earlier, since-
  abandoned session (e.g. this button was clicked, then the page was
  reloaded) is still surfaced and followed through to completion without
  requiring another click.
- **`panel/Toast.tsx`**: a small fixed-position, `user-select: none`
  bottom-center notification (blue/green/red by variant) used only by
  `RefreshDataButton` right now — not a global toast system.
- **`data/markerColors.ts`**: `colorFor()` (blue/orange/green by how many
  of stamp+badge are collected) and `matchesFilters()` (OR semantics
  across the two "not yet collected" filters) both operate directly on a
  `Location`'s `stamp`/`badge` fields — no separate state-map/lookup layer.
- **`hooks/useLocations.ts`**: fetches once on mount; exposes `setLocations`
  so `useToggleCollected` can apply optimistic updates in place. Also
  exposes `refreshOne(id)` — a targeted `?id=eq.<id>&select=id,stamp,badge`
  fetch (not a full re-fetch of all ~136 rows) that `App.tsx` calls in a
  `useEffect` whenever a marker's detail panel opens, so a `stamp`/`badge`
  toggled on a different device is picked up without a manual reload.
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

## Android app (`android/`)

Personal-sideload-only wrapper (`com.aqoursmachiaruki.app`, not published
to Google Play) whose only job is to open the deployed `web/` site
fullscreen. Standalone Gradle/Kotlin project, unrelated to `web/`'s or
`pipeline/`'s toolchains.

- **Why a Trusted Web Activity, not a `WebView`**: the site gates
  everything behind Auth0 → Google login. Google blocks OAuth sign-in
  inside plain embedded `WebView`s, so a raw `WebView` wrapper gets stuck
  at the login screen. A Trusted Web Activity (TWA) hosts real Chrome
  under the hood — same as the browser — just without Chrome's own
  toolbar, so Google OAuth works normally.
- **`MainActivity.kt`** launches the TWA via `TwaLauncher`
  (`com.google.androidbrowserhelper:androidbrowserhelper`), which pushes
  the browser activity onto the **same task** as `MainActivity` (not a
  separate one). Two consequences that are easy to get wrong (both
  confirmed via `adb logcat` during development, not just theorized):
  - Must **not** `finish()` right after launching — that races with the
    browser activity still attaching to the task and aborts the
    load/crashes on cleanup. `MainActivity` stays alive underneath and
    only finishes in `onRestart()` (i.e. once the user backs out of the
    browser and control actually returns here), mirroring Google's own
    reference `androidbrowserhelper` `LauncherActivity`.
  - Icon rotation (see below) must only happen in `onDestroy()`, never
    right after launching. Disabling the `activity-alias` that launched
    the *current* task closes that entire task immediately — both
    `MainActivity` and the TWA/Custom Tab riding on top of it — regardless
    of the `DONT_KILL_APP` flag (which only protects the process, not the
    task/activity stack). Rotating any earlier silently kills the site
    mid-load.
- **Icon rotation**: nine `activity-alias` entries in
  `AndroidManifest.xml` (one per Aqours member,
  `res/mipmap-xxxhdpi/ic_launcher_<name>.png`), all targeting the same
  `MainActivity`. Exactly one is enabled at a time; `rotateIcon()`
  (called from `onDestroy()`) picks a different one at random via
  `PackageManager.setComponentEnabledSetting`. The visible home-screen
  icon only catches up the *next* time that particular launcher redraws
  it — some launchers cache it and lag behind the actual enabled state by
  a few opens; that's a launcher-side quirk, not a bug in the rotation
  logic.
- **Fullscreen (no Custom Tab toolbar) requires domain verification**:
  `web/public/.well-known/assetlinks.json` declares the app's package
  name and its signing certificate's SHA-256 fingerprint. Chrome checks
  this at runtime and falls back to a normal Custom Tab automatically if
  verification fails or is stale — a mismatch degrades gracefully rather
  than breaking the app.
- Signed with a **dedicated keystore** (`android/keystore/release.jks`,
  gitignored) rather than the machine-local auto-generated debug
  keystore, specifically so the fingerprint in `assetlinks.json` stays
  valid across machines/reinstalls. Credentials live in
  `android/keystore.properties` (gitignored, same pattern as
  `pipeline/.env`/`web/.env.local`); `app/build.gradle.kts` reads it and
  signs **both** debug and release build types with it.
- `androidx.browser` is pinned to `1.8.0` and `androidbrowserhelper` to
  `2.5.0` deliberately — newer releases of either pull in transitive
  dependencies requiring `compileSdk 36`+/AGP 8.9+, which this project
  doesn't use.

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
