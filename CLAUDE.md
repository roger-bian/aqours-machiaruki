# CLAUDE.md

Guidance for Claude Code working in this repo.

## What this is

Numazu (沼津) "machiaruki" stamp-rally map: Love Live! Sunshine!! stamp
locations from a public Google My Maps KML export. Five pieces:

1. **`web/`** — static React + Vite + Leaflet frontend. Numbered
   color-coded markers (color = collection progress), tap-to-open centered
   detail panel (photo, member, address, hours, holidays, スタンプ/缶バッジ
   checkboxes), top-right filter panel. Reads location data directly from
   Supabase's REST API (PostgREST) — no KML parsing/pipeline logic here.
2. **`pipeline/`** — FastAPI service owning the data pipeline (download
   KML → clean/parse → download photos → upsert Postgres, upload photos to
   Supabase Storage). Runs only on `POST /pipeline/run`.
3. **`android/`** — personal-sideload-only Android wrapper (not on Google
   Play), opens deployed `web/` site fullscreen via Trusted Web Activity.
   See "Android app" below.
4. **Supabase** (Postgres + Storage) — `locations` table
   (`db/supabase_schema.sql`) + photo bucket.
5. **Auth0** — personal app, small email allowlist, Google login only.
   Auth0 authenticates; Supabase trusts that Auth0 tenant as
   **Third-Party Auth** provider (Dashboard > Authentication >
   Third-Party Auth) so RLS evaluates the real Auth0 ID token, not a
   static key. `pipeline/` independently verifies the same ID token
   against Auth0's JWKS for `/pipeline/run`. See "Auth" below.

`db/` + `postgrest/`: also a **local** Postgres + standalone PostgREST
setup (no Docker/Supabase CLI) for dev against a local DB before Supabase
— `db/schema.sql` vs `db/supabase_schema.sql` (latter adds RLS policies
PostgREST expects; local uses plain `GRANT`s instead).

## Environment & commands

- **`pipeline/`**: pyenv virtualenv `aqours` (`.python-version`), Python
  3.10. `pip install -r pipeline/requirements.txt`. GDAL needs the native
  lib first (`sudo apt-get install libgdal-dev gdal-bin`); pinned `GDAL==`
  version must match `gdal-config --version`. Run:
  `cd pipeline && uvicorn app.main:app --port 8000`. Trigger: needs a
  valid Auth0 ID token (see "Auth") —
  `curl -X POST http://localhost:8000/pipeline/run -H "Authorization: Bearer <token>"`.
  Credentials in `pipeline/.env` (gitignored) — see README.md for keys.
- **`web/`**: `cd web && npm install && npm run dev` (Vite, port 5173+).
  `npm run build` for a prod build. Credentials in `web/.env.local`
  (gitignored).
- **`android/`**: needs JDK 17 + Android SDK command-line tools
  (`platform-tools`, `platforms;android-34`, `build-tools;34.0.0`),
  pointed to via `android/local.properties`'s `sdk.dir` (gitignored,
  machine-specific). Build: `cd android && ./gradlew assembleDebug`.
  Sideload: `adb install -r app/build/outputs/apk/debug/app-debug.apk`.
  Signing keystore creds in `android/keystore.properties` (gitignored) —
  see README.md for setup + wiring `web/public/.well-known/assetlinks.json`.
- No test suite/linter beyond `tsc`/`oxlint` defaults in `web/`.
- Root `render.yaml`: two Render services, both auto-deploy on push.
  `aqours-machiaruki-pipeline` (`pipeline/Dockerfile`, Docker, free plan,
  `buildFilter` scoped to `pipeline/**`). `aqours-machiaruki-web`
  (`runtime: static`, `rootDir: ./web`, `npm ci && npm run build`, no
  `buildFilter` — redeploys every push). Pipeline container stateless —
  everything persistent lives in Supabase, not local disk. `envVars`:
  `sync: false` for secrets (set once in Render dashboard), plain
  `value:` for non-secret Auth0 domain/client ID (see "Auth").

## Development workflow

- Start `pipeline`/`web` dev servers only on demand for local testing,
  not proactively.
- Pipeline change → usually no need to re-trigger `/pipeline/run` unless
  KML-parsing/upsert logic changed — frontend reads Supabase directly.
- Frontend changes verified manually by the user unless stated otherwise.

## Git commit conventions

- Group changes by logical category (one feature/fix per commit); commit
  each separately, not as one large commit.
- Never roll back/discard current repo state (`git reset`/`checkout`/
  `stash`) to reconstruct cleaner category splits — work forward from the
  working tree as-is.
- If a file's uncommitted state belongs to a new category but overlaps an
  earlier one, don't split that file's diff — current state/category
  wins, earlier category's changes to that file roll into this commit.

## Data pipeline (`pipeline/`)

1. **`app/kml.py`**: `fetch_kml()` downloads fresh every call.
   `os.environ['OGR_SKIP'] = 'LIBKML'` set **at the top of the file,
   before the `geotable`/`osgeo` import** — forces GDAL's built-in KML
   driver over `LIBKML` (which `libgdal-dev` installs and GDAL otherwise
   prefers). Load-bearing: `geotable` hardcodes a drop-list deleting
   lowercase `description`; the built-in driver exposes it capitalized
   (`Description`), which survives and is what `description.py` expects.
   Remove this line → image/address/hours/member parsing silently
   breaks, no error.
2. **`app/description.py`**: `parse_description()` parses each
   placemark's `Description` HTML (`<img>` +
   `メンバー／`/`住所／`/`営業時間／`/`定休日／` labels in a CDATA blob).
   Fields located **by string position**, not fixed-neighbor assumption
   — some entries omit the member/hours label. Missing → empty
   string/`'なし'`, not a raise. Touching this: recheck entries missing
   labels, not just the common case.
3. **`app/images.py`**: `cache_images()` hashes each photo URL (SHA1) as
   the Storage object key (`app/storage.py`) — `object_exists()` checked
   first; photo fetched from Google's `mymaps.usercontent.google.com` CDN
   (blocks/rate-limits repeats) only on a miss, uploaded via
   `upload_object()` (`x-upsert: true`). Storage *is* the dedupe cache —
   no local disk, since Render's free-plan container has none and a
   restart/redeploy would lose it. Frontend reads the `img_url` column
   (Storage public URL), not a local path.
4. **`app/validation.py`**: `validate_structure()` checks a fresh KML
   against the *previous* successful run's KML ("accepted structure"
   baseline) before any DB write — required columns present, every
   placemark has a name + Point geometry, placemark count hasn't dropped
   past `MIN_COUNT_RATIO` of baseline, address/image extraction hasn't
   broken past `MAX_EMPTY_ADDRESS_RATIO`/`MAX_EMPTY_IMG_RATIO`. Raises
   `PipelineValidationError` on deviation; `app/main.py` → HTTP 422,
   discards the download, DB/baseline untouched. First-ever run (no
   baseline): count-drop check skipped, rest still applies.
5. **`app/db.py`**: `upsert_locations()` upserts on natural key
   `(name, lat, lon)`. Never touches `stamp`/`badge` — not in the
   `INSERT` columns (new rows get defaults, both `false`), not in
   `ON CONFLICT DO UPDATE SET` (existing rows keep their state). Pipeline
   owns everything except collection state, which only the frontend
   writes — don't add `stamp`/`badge` to this query.
6. **`app/main.py`** / **`app/pipeline_state.py`**: `POST /pipeline/run`
   requires a valid Auth0 ID token (`app/auth.py`'s
   `verify_auth0_token`, see "Auth"), then a fast lock-protected
   check-and-kickoff, returning almost immediately —
   `{'status': 'started'}` or `{'status': 'already_running'}` — not
   blocking for the full run. Actual work (`_execute_pipeline_run`, same
   fetch/validate/cache/upsert logic) runs via FastAPI `BackgroundTasks`.
   `pipeline_state` holds shared in-memory `running`/`last_result`/
   `last_error` behind a `threading.Lock` (atomic across thread-pool
   handlers) — not persisted, so a restart mid-run self-heals to "not
   running." `GET /pipeline/status` exposes state for polling. A
   rejected/failed run leaves DB/baseline untouched as before — only
   *when* the pipeline runs/reports changed, not the validation/rollback
   semantics. Baseline KML stored in Supabase Storage
   (`BASELINE_KML_KEY = '_pipeline/baseline.kml'`, same bucket), not
   local disk. `tempfile` used only as scratch space for
   `geotable.load()` to parse KML bytes from Storage/Google; nothing
   persists locally across requests.

## Frontend (`web/src`)

- **`data/types.ts`**: `Location` type mirrors the Postgres row exactly
  (incl. `stamp`/`badge`) — PostgREST returns all columns by default, no
  separate mapping layer.
- **`data/supabaseRest.ts`**: shared `API_BASE`/`authHeaders()` for
  `useLocations` (GET) and `useToggleCollected` (PATCH). Swapping
  Supabase projects = two-env-var change here, not code. `authHeaders()`
  is `async` — sources `Authorization` from a live Auth0 ID token via a
  registered getter (`registerIdTokenGetter()`), not a static key;
  `apikey` still sends the static publishable key (Supabase's gateway
  needs it for routing regardless of auth method).
- **`auth/AuthGate.tsx`**: wraps the whole app (`main.tsx`, inside
  `Auth0Provider`). Nothing renders behind it until Auth0 login succeeds
  (`loginWithRedirect` with `connection: 'google-oauth2'`, skips
  account-chooser) — an Auth0 Action server-side denies all but the
  owner's email, so a real gate, not just client-side. Once
  authenticated, `useEffect` calls `registerIdTokenGetter()` so
  `supabaseRest.ts` gets a fresh ID token per request.
- **`panel/RefreshDataButton.tsx`**: the "データ更新" button — calls
  `useAuth0().getIdTokenClaims()` directly, `POST`s the raw ID token to
  `VITE_PIPELINE_API_BASE`'s `/pipeline/run` (independently verified, see
  "Auth"). Request returns almost immediately (`'started'`/
  `'already_running'` — backend runs the pipeline after, not inline), so
  the button's loading state only covers that round-trip; a `Toast`
  reports which; `pollUntilDone()` (`GET /pipeline/status` ~3s) picks up
  the eventual result either way — success → toast +
  `window.location.reload()` after dismiss, error → error toast. A
  mount-time effect does the same status check (no `POST`) so a run left
  in progress by an abandoned session (button clicked, page reloaded)
  still surfaces without another click.
- **`panel/Toast.tsx`**: small fixed-position, `user-select: none`
  bottom-center notification (blue/green/red), used only by
  `RefreshDataButton` — not a global toast system.
- **`data/markerColors.ts`**: `colorFor()` (blue/orange/green by
  stamp+badge collected count), `matchesFilters()` (OR semantics across
  the two "not yet collected" filters) — both operate directly on
  `Location`'s `stamp`/`badge`, no state-map layer.
- **`hooks/useLocations.ts`**: fetches once on mount; exposes
  `setLocations` for `useToggleCollected`'s optimistic updates. Also
  `refreshOne(id)` — targeted `?id=eq.<id>&select=id,stamp,badge` fetch
  (not a full ~136-row re-fetch), called by `App.tsx` on marker
  detail-panel open, so cross-device `stamp`/`badge` changes pick up
  without a reload.
- **`hooks/useToggleCollected.ts`**: checkbox toggle optimistically
  updates local state, `PATCH`es Supabase, rolls back on failure. Tracks
  in-flight `(id, field)` pairs (via a `ref`, not just `state`, avoiding a
  same-tick race) so a rapid double-click can't fire overlapping
  requests — `DetailPanel` disables + spinners a checkbox while its
  write is pending.
- **`map/MapView.tsx`** / **`map/markerIcon.ts`**: Leaflet markers use
  `L.divIcon` (colored circle + number), memoized on `[color, number]`.
  No Leaflet `Popup` — `DetailPanel` is a plain fixed-position React div,
  centered in the viewport rather than anchored to the tapped marker
  (mobile-friendly, no hover on touch).
- **`panel/Backdrop.tsx`**: dimmed full-screen div while the panel is
  open; tap closes it. Needed since marker clicks bubble to Leaflet's own
  map click handler — without this, a tap opens then immediately closes
  the panel.
- **`hooks/useUserLocation.ts`**: browser Geolocation API
  (`getCurrentPosition`, one-shot, not `watchPosition`).
  Denied/unsupported → no error, just no current-location marker.
- Leaflet's zoom control defaults top-left — filter panel positioned
  top-right (`FilterPanel.tsx`) to avoid overlap.

## Android app (`android/`)

Personal-sideload-only wrapper (`com.aqoursmachiaruki.app`, not on Google
Play); only job is opening the deployed `web/` site fullscreen. Standalone
Gradle/Kotlin project, unrelated to `web/`/`pipeline/` toolchains.

- **Why TWA, not `WebView`**: the site gates everything behind Auth0 →
  Google login. Google blocks OAuth sign-in inside embedded `WebView`s,
  so a raw `WebView` wrapper sticks at login. A Trusted Web Activity
  (TWA) hosts real Chrome under the hood — same as the browser, just no
  Chrome toolbar — so Google OAuth works normally.
- **`MainActivity.kt`** launches the TWA via `TwaLauncher`
  (`androidbrowserhelper`), which pushes the browser activity onto the
  **same task** as `MainActivity` (not a separate one). Two gotchas
  (confirmed via `adb logcat`, not just theorized):
  - Must **not** `finish()` right after launching — races with the
    browser activity still attaching, aborts the load/crashes on
    cleanup. `MainActivity` stays alive underneath, finishes only in
    `onRestart()` (once the user backs out of the browser and control
    returns) — mirrors Google's reference `androidbrowserhelper`
    `LauncherActivity`.
  - Icon rotation (below) only in `onDestroy()`, never right after
    launch. Disabling the `activity-alias` that launched the *current*
    task closes that whole task immediately — both `MainActivity` and
    the TWA/Custom Tab on top — regardless of `DONT_KILL_APP` (protects
    the process only, not the task/activity stack). Rotating earlier
    silently kills the site mid-load.
- **Icon rotation**: nine `activity-alias` entries in
  `AndroidManifest.xml` (one per Aqours member,
  `res/mipmap-xxxhdpi/ic_launcher_<name>.png`), all targeting
  `MainActivity`. Exactly one enabled at a time; `rotateIcon()` (called
  from `onDestroy()`) picks a different one at random via
  `PackageManager.setComponentEnabledSetting`. Home-screen icon catches
  up only next time that launcher redraws — some launchers cache/lag a
  few opens behind actual state; a launcher quirk, not a rotation bug.
- **Fullscreen (no Custom Tab toolbar) needs domain verification**:
  `web/public/.well-known/assetlinks.json` declares the package name +
  signing cert SHA-256 fingerprint. Chrome checks this at runtime, falls
  back to a normal Custom Tab if verification fails/stale — degrades
  gracefully.
- Signed with a **dedicated keystore** (`android/keystore/release.jks`,
  gitignored), not the machine-local debug keystore, so the
  `assetlinks.json` fingerprint stays valid across machines/reinstalls.
  Creds in `android/keystore.properties` (gitignored, same pattern as
  `pipeline/.env`/`web/.env.local`); `app/build.gradle.kts` signs **both**
  debug and release build types with it.
- `androidx.browser` pinned to `1.8.0`, `androidbrowserhelper` to
  `2.5.0` deliberately — newer releases pull transitive deps requiring
  `compileSdk 36`+/AGP 8.9+, which this project doesn't use.

## Auth (Auth0 + Supabase)

Personal app, small email allowlist — only those emails can ever
read/write data, enforced at the data layer, not just client-side.
Addresses kept out of the repo: `pipeline/app/auth.py` reads
`ALLOWED_EMAILS` (comma-separated, `pipeline/.env` locally / `sync: false`
in `render.yaml`); the Auth0 Action (dashboard-only, not in repo)
enforces the same allowlist independently.

- **Auth0** authenticates via Google login (`google-oauth2`). An Auth0
  Action (`onExecutePostLogin`, dashboard, not in repo) denies login
  outright outside the allowlist, stamps `role: 'authenticated'` onto the
  **ID token** (Auth0 strips unnamespaced custom claims from *access*
  tokens — why the ID token, not the access token, is what's passed
  around everywhere here).
- **Supabase** configured as a Third-Party Auth provider trusting that
  Auth0 tenant directly (Dashboard > Authentication > Third-Party Auth,
  external to repo) — PostgREST verifies the Auth0 ID token against
  Auth0's JWKS, assigns the `authenticated` Postgres role from the
  `role` claim. `db/supabase_schema.sql`'s RLS policies/grants are
  `TO authenticated` only — `anon` gets nothing, a deliberate change from
  the old fully-permissive `anon` model.
- **`pipeline/app/auth.py`**: independently verifies the same Auth0 ID
  token for `POST /pipeline/run` (`PyJWKClient` against Auth0's JWKS,
  checks signature/issuer/audience/email) — separate from/unrelated to
  Supabase's Third-Party Auth trust; both just happen to trust the same
  tenant. Deliberately **not** a static shared secret: the frontend's
  "データ更新" button calls this endpoint directly from the browser, and
  anything baked into the Vite bundle (`VITE_*`) is effectively public
  once loaded.
- `web/`'s `VITE_AUTH0_DOMAIN`/`VITE_AUTH0_CLIENT_ID` and `pipeline/`'s
  `AUTH0_DOMAIN`/`AUTH0_CLIENT_ID` are **not secrets** — meant to be
  public in an SPA bundle — plain `value:` entries in `render.yaml`, not
  `sync: false`.
- `useRefreshTokens` + `cacheLocation: 'localstorage'` (`main.tsx`'s
  `Auth0Provider`) avoid Auth0's legacy iframe silent-auth, which
  third-party-cookie blocking (Safari/Chrome) increasingly breaks —
  matters since the app is used in real walking-around-Numazu phone
  sessions, not just desktop.
- `pipeline/`'s CORS (`app/main.py`) scoped to the real frontend
  origin(s), not `allow_origins=['*']` — cross-origin requests now carry
  an `Authorization` header, so a wildcard origin isn't appropriate.

## Supabase-specific notes

- API key naming: Supabase's dashboard calls the `anon` key the
  **publishable key**, `service_role` key the **secret key**.
  `pipeline/` uses the secret key (Storage uploads); `web/` uses the
  publishable key only for the `apikey` header (routing, not identity —
  see "Auth").
- Local Postgres setup (`db/schema.sql`) skips RLS entirely (plain
  `GRANT`s to `web_anon`), unaffected by any of the above — dev-only
  scaffolding, never deployed, no Auth0 involved.
