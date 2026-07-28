# CLAUDE.md

Guidance for Claude Code working in this repo.

## What this is

Numazu (沼津) "machiaruki" stamp-rally map: Love Live! Sunshine!! stamp
locations from a public Google My Maps KML export. Five pieces:

1. **`web/`** — static React + Vite + Leaflet frontend. Numbered markers
   with two independent visual channels — fill = collection progress, ring
   = open/closed right now — tap-to-open centered detail panel (photo,
   member, address, hours, holidays, open-status badge, スタンプ/缶バッジ
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
- **Tests**: `make test` runs both suites (~2s, fully offline — no network,
  no DB). `make test-py` = `cd pipeline && python -m pytest`; `make test-web`
  = `cd web && npm test` (vitest). pytest needs
  `pip install -r pipeline/requirements-dev.txt` once; it is deliberately not
  in `requirements.txt` so `pipeline/Dockerfile`'s image stays slim. Linting
  is still just `tsc`/`oxlint` defaults in `web/`. See "Tests" below for what
  is covered and the traps in writing more.
- **`PIPELINE_DATABASE_URL` in `pipeline/.env` points at the live
  Supabase**, not a local Postgres — a locally-run pipeline writes to
  production. There is no separate staging DB.
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
- Schema changes: apply the `ALTER TABLE ... IF NOT EXISTS` line via the
  Supabase SQL Editor **before** pushing pipeline changes that write the
  new column (Render auto-deploys on push). Don't paste the whole
  `db/supabase_schema.sql` — `CREATE POLICY` has no `IF NOT EXISTS` and
  errors on any project where the policies already exist.

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
   labels, not just the common case. Returns **both** the display strings
   (`hours`/`holidays`, cosmetically normalized) and the untouched
   `raw_hours`/`raw_holidays` — `app/hours.py` content-addresses the raw
   text, so normalizing first would make its hash depend on this
   function's cosmetic choices. `holidays` keeps **every** `<br>` line; it
   used to be `.split('<br>')[0]`, which silently dropped the
   `※閉店により、終了しました。` marker on the 8 closed shops.
3. **`app/images.py`**: `cache_images()` hashes each location's **natural
   key** (`name|lat|lon`, SHA1) as the Storage object key
   (`app/storage.py`) — *not* the photo URL. Google embeds a per-request
   token in that URL, so it differs on every KML fetch; keying on it meant
   the cache never hit and every run silently re-uploaded a duplicate of
   every photo. `object_exists()` checked first; photo fetched from
   Google's `mymaps.usercontent.google.com` CDN (blocks/rate-limits
   repeats) only on a miss, uploaded via `upload_object()`
   (`x-upsert: true`). Storage *is* the dedupe cache — no local disk, since
   Render's free-plan container has none and a restart/redeploy would lose
   it. Frontend reads the `img_url` column (Storage public URL), not a
   local path.
4. **`app/validation.py`**: `validate_structure()` checks a fresh KML
   against the *previous* successful run's KML ("accepted structure"
   baseline) before any DB write — required columns present, every
   placemark has a name + Point geometry, placemark count hasn't dropped
   past `MIN_COUNT_RATIO` of baseline, address/image/hours extraction
   hasn't broken past `MAX_EMPTY_ADDRESS_RATIO`/`MAX_EMPTY_IMG_RATIO`/
   `MAX_EMPTY_HOURS_RATIO`. The hours check guards *extraction* only — a
   run where many rows fall back to the rule-based parse tier is reported
   via `unverified`, never rejected. Raises
   `PipelineValidationError` on deviation; since the run is a background
   task the triggering request has already returned, so `app/main.py`
   records it as `last_result: 'error'` for `GET /pipeline/status` to pick
   up (no HTTP error code), discards the download, DB/baseline untouched.
   First-ever run (no baseline): count-drop check skipped, rest still
   applies.
5. **`app/hours.py`**: `parse_hours_holidays()` turns the freeform
   Japanese `営業時間`/`定休日` into the structured `hours_json` column.
   See "Business hours" below — it's the most involved parsing in the
   repo and has its own section.
6. **`app/db.py`**: `upsert_locations()` upserts on **`id`, which is the
   placemark's 1-based position in the KML** — that position *is* the stamp
   number the map renders (`MapView.tsx` labels each marker `loc.id`), so
   `id` is domain data, not a surrogate key. Derived from the caller's list
   order via `enumerate(records, start=1)`, never read off the record, so
   `records` must arrive in KML order and be the complete set —
   `_build_records()` builds it straight from `placemarks.iterrows()`, which
   preserves document order. Never touches `stamp`/`badge` — not in the
   `INSERT` columns (new rows get defaults, both `false`), not in
   `ON CONFLICT DO UPDATE SET` (existing rows keep their state). Pipeline
   owns everything except collection state, which only the frontend
   writes — don't add `stamp`/`badge` to this query. `name`/`lat`/`lon`
   *are* in `DO UPDATE SET`: the row at position N must follow the KML if
   its text changes. `hours_json` is passed through `psycopg2.extras.Json`
   at execute time so callers hand over a plain dict and never think about
   serialization. Returns `(inserted, updated)` — `app/main.py` now uses it
   rather than discarding it.
   **Why not the `(name, lat, lon)` natural key it used to key on**:
   `name` isn't stable. Two placemarks carry a literal newline in their
   `<name>` (`海鮮丼と魚河岸定食\nかもめ丸`,
   `ラブライブ！サンシャイン!!\nプレミアムショップ`) and one run emitted them
   space-joined instead. The natural key missed the existing rows and
   `INSERT`ed duplicates, which took `nextval()` — by then in the 1400s,
   because `ON CONFLICT DO UPDATE` evaluates column defaults *before* it
   detects the conflict, so every run burned one sequence value per
   placemark even when it only updated. Net effect: phantom markers
   numbered **1411** and **1478** beside the real 51 and 118, collection
   state stranded on the originals. Keying on position fixes both halves —
   a rename updates the row where it already is, and supplying `id`
   explicitly means the sequence is never touched. The table's old
   `UNIQUE (name, lat, lon)` was dropped along with it — on an unstable
   `name` it only stood to wedge future runs. Still uncovered: a
   location *leaving* the KML leaves a stale trailing row at an id past the
   new count (nothing deletes rows; `validate_structure` only blocks a
   count drop past `MIN_COUNT_RATIO`).
7. **`app/main.py`** / **`app/pipeline_state.py`**: `POST /pipeline/run`
   requires a valid Auth0 ID token (`app/auth.py`'s
   `verify_auth0_token`, see "Auth"), then a fast lock-protected
   check-and-kickoff, returning almost immediately —
   `{'status': 'started'}` or `{'status': 'already_running'}` — not
   blocking for the full run. Actual work runs via FastAPI
   `BackgroundTasks`: `_run_pipeline()` does the fetch/validate/cache/upsert
   and **raises**, while `_execute_pipeline_run()` is a thin wrapper that
   only reports. Keep it that way — **every** path must call
   `pipeline_state.finish()` exactly once. An escaping exception leaves
   `running` set with nothing to clear it, so every later trigger answers
   `already_running` until the container restarts, and the request that
   started the run already returned 200 so nothing surfaces the wedge.
   (Regression: the baseline download and the final baseline upload used to
   sit outside the `try`.)
   `pipeline_state` holds shared in-memory `running`/`last_result`/
   `last_error`/`last_details` behind a `threading.Lock` (atomic across
   thread-pool handlers) — not persisted, so a restart mid-run self-heals
   to "not running." `last_details` carries
   `{inserted, updated, unverified}` from a successful run; `unverified`
   counts rows whose schedule came from the rule-based tier rather than a
   hand-reviewed override, and `RefreshDataButton` surfaces it in the
   toast. `GET /pipeline/status` exposes state for polling. A
   rejected/failed run leaves DB/baseline untouched as before — only
   *when* the pipeline runs/reports changed, not the validation/rollback
   semantics. Baseline KML stored in Supabase Storage
   (`BASELINE_KML_KEY = '_pipeline/baseline.kml'`, same bucket), not
   local disk. `tempfile` used only as scratch space for
   `geotable.load()` to parse KML bytes from Storage/Google; nothing
   persists locally across requests.

## Business hours (`pipeline/app/hours.py` → `hours_json`)

The KML's `営業時間`/`定休日` are freeform Japanese. `parse_hours_holidays()`
turns them into a structured schedule the frontend evaluates against a
clock. Measured against the live 136-placemark KML: 106 fully determined by
rules, 8 `年中無休`-only → 24h, 13 with `不定休`/`臨時休館` closures, 8
permanently closed, 1 with no `営業時間` label at all. (The harness reports
`irregular: 16` — those 13 plus 3 more the override file flags for
maintenance closures or an unstated end time.)

**The residual is not a parser weakness** — `不定休` means "irregular
holidays" and no parser, LLM included, can extract a schedule that was never
written down. Design goal is *honest* status, not maximal coverage:
`unknown` is a first-class outcome.

- **Three-tier lookup**, keyed by `sha1(raw_hours \x1f raw_holidays)[:16]`:
  `verified` (hand-reviewed entry in `app/hours_parsed.json`) → `manual`
  (same file; local knowledge the source does *not* state — currently only
  三交イン 沼津駅前, a hotel with no `営業時間` label) → `auto` (rule-based
  fallback, always available).
- **Why tier 1 exists**: the rule tier strips **all** parentheticals as
  noise (that's how it discards `（最終入園15:30）`/`(L.O.16:30)`), so it
  also discards genuine conditionals like `（木曜日は14:00まで）`. ~6 entries
  carry real hours inside parentheses. Without the override, びゅうお shows
  a green ring at 16:00 on a Thursday when it shut at 14:00 — the rule tier
  fails *confidently*, not loudly. That's what `unverified` is for.
- **Content-addressed on the raw text**, so identical source text dedupes
  (136 locations → 125 keys; 7 hotels share `年中無休`/`なし`) — hence
  `_names` is an array. An absent field still hashes fine, which is what
  makes the 三交イン `manual` entry stable across runs.
- **A hash miss never creates a new DB row.** The upsert key is `id` (the
  KML position); the hash only indexes the override file. A miss (new
  location, or upstream text edited) just recomputes `hours_json` from the
  rule tier and bumps `unverified`. An edited entry *should* stop matching —
  a hand-written override must not keep overriding changed source data.
- **Intervals are minutes from midnight** (`600` = 10:00). `11:00～26:00`
  becomes `[660, 1560]`; the frontend looks back a day for `end > 1440` so
  01:00 still reads as open.
- **Tokenize weekdays before anything else** (`_tokenize_days`). `日` means
  both "Sunday" and the suffix in `曜日`/`1月1日`, and compound words must be
  consumed whole — the `日` inside `平日`/`土日`/`日祝` otherwise gets eaten
  as Sunday, so `平日・土曜` parsed as `平@sun・@sat`, silently losing all
  five weekdays. This was the single largest source of wrong parses.
- Other load-bearing details: parentheticals are stripped **before** `※`
  notes (`平日（※祝日を除く）10:00~20:00` has a `※` inside the brackets, and
  stripping to end-of-line first eats the range after them); day scope is
  read as the text *between* consecutive time ranges, not by splitting on
  punctuation (`月・火・木・金・土7:00~13:00　日・祝日9:00~13:30` separates two
  scopes with only a space); `昼休み` ranges are dropped rather than added as
  opening hours.
- **Regenerate** with `cd pipeline && python tools/gen_hours_overrides.py`.
  Existing keys keep their committed entry, so hand corrections survive; only
  new/changed keys get a fresh rule-based baseline. The `CORRECTIONS` dict in
  that script is where the *rationale* for each hand-fix lives.
- **Review harness**: `cd pipeline && python -m app.hours` prints every
  entry's parse next to its raw text and flags days with no hours that
  aren't a stated 定休日. It fetches the **live** KML, so it's the tool for
  eyeballing *new* upstream text — not a change gate. For that use
  `make test`: `tests/test_hours_golden.py` runs the same checks offline
  over the committed corpus, including the `!!` gap flag (see "Tests").

## Frontend (`web/src`)

- **`data/types.ts`**: `Location` type mirrors the Postgres row exactly
  (incl. `stamp`/`badge` and `hours_json`) — PostgREST returns all columns
  by default, no separate mapping layer. A `jsonb` column arrives as **real
  nested JSON**, so `hours_json.weekly.thu` is a live array with no parse
  step and no fetch change.
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
- **`data/markerColors.ts`**: single choke point for both colour and
  filtering. `colorFor()` (blue/orange/grey by stamp+badge count) is the
  marker **fill**; `ringColorFor()` maps an `OpenStatus` to the **ring**
  (green open / amber closing within 2h / red closed / black permanently
  closed / `null` unknown → no ring drawn). Two independent channels —
  don't fold open-status into the fill. `matchesFilters()` takes `now` and
  **AND**s its filters (this changed from OR when the panel went to one
  checkbox per *concept* rather than per *field*).
- **`data/openStatus.ts`**: `openStatusFor(hours_json, now)` — pure, no
  side effects. Order matters: `permanently_closed` short-circuits before
  the clock (a shut shop is never "open"), then `always_open` (a 24h place
  must never read `closing_soon`), then closed-dates/closed-days/nth-week,
  then today's intervals, then yesterday's `end > 1440` overnight shifts.
  All dates resolved in **Asia/Tokyo** via `Intl.DateTimeFormat`, never the
  device timezone — the shops are in Numazu wherever the phone thinks it
  is. `@holiday-jp/holiday_jp` supplies 祝日 (incl. 振替休日 and the
  astronomical 春分/秋分), needed because the source text treats 祝日 as its
  own category (`土日祝`, `日曜日・祝日`); `isHoliday()` takes a `YYYY-MM-DD`
  string, which sidesteps Date/timezone conversion entirely. ~13 kB gzipped.
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
  `L.divIcon` (colored circle + number), memoized on
  `[color, number, ring]` — the ring must be in the cache key or markers
  keep their first-rendered status forever. The ring is a `box-shadow`,
  not a `border`, so the disc keeps its full diameter and the number stays
  centred whether or not a ring is drawn. No Leaflet `Popup` —
  `DetailPanel` is a plain fixed-position React div, centered in the
  viewport rather than anchored to the tapped marker (mobile-friendly, no
  hover on touch).
- **`panel/Backdrop.tsx`**: dimmed full-screen div while the panel is
  open; tap closes it. Needed since marker clicks bubble to Leaflet's own
  map click handler — without this, a tap opens then immediately closes
  the panel.
- **`hooks/useUserLocation.ts`**: browser Geolocation API
  (`getCurrentPosition`, one-shot, not `watchPosition`).
  Denied/unsupported → no error, just no current-location marker.
- **`App.tsx`**: holds a `now` state ticking every 60s. **Load-bearing** —
  without it the `visibleLocations` memo and `markerIcon`'s module-level
  cache both freeze at page-load time, so rings and the `営業中のみ` filter
  would never update as the clock advances. `now` is threaded to
  `MapView`, `DetailPanel`, and the filter memo's deps.
- **`panel/FilterPanel.tsx`**: exactly two flat checkboxes, `未獲得`
  (`!stamp || !badge`) and `営業中のみ` (status `open` or `closing_soon`),
  no group headers. They **stack (AND)**. `App.tsx`'s `FILTER_KEYS`
  validates stored keys, so the pre-existing
  `['stamp_missing','badge_missing']` localStorage value is silently
  dropped on load — no migration code needed.
- **`panel/DetailPanel.tsx`**: `StatusBadge` renders the computed status
  directly **above** the raw Japanese it was derived from, so a bad parse
  is visible during ordinary use rather than only when someone goes
  looking. `irregular` notes render as ⚠ caveat lines; a
  `permanently_closed` location gets a struck-through grey title.
- Leaflet's zoom control defaults top-left — filter panel positioned
  top-right (`FilterPanel.tsx`) to avoid overlap.

## Tests

`make test` → `pipeline/tests/` (pytest) + `web/src/data/*.test.ts` (vitest).
Both fully offline: verified to pass with `socket.connect` blocked and with
`pipeline/.env` renamed away. Total ~2s, so it's a per-change gate, not a CI
ritual.

- **The suite must never reach production.** `PIPELINE_DATABASE_URL` points at
  the live Supabase and there's no staging DB, so `tests/conftest.py` stubs
  `psycopg2.connect` to raise for every test (an autouse fixture) and sets
  dummy env vars. **`load_dotenv()` doesn't override already-set vars**, which
  is what makes conftest's values win over the real `pipeline/.env`.
- **`conftest.py`'s import order is load-bearing.** Env vars are set at module
  top *before* any `app.*` import (`app/auth.py` reads three of them with bare
  `os.environ[...]` at module level), then `import app.kml` runs *before*
  anything can pull in geotable/osgeo, so its `OGR_SKIP` write lands before
  GDAL locks in a driver.
- **`TestClient` runs `BackgroundTasks` synchronously** before returning the
  response. A `POST /pipeline/run` test that doesn't monkeypatch
  `app.main._execute_pipeline_run` runs the real pipeline against production.
- **Patch `app.images.*`, not `app.storage.*`** — `app/images.py` does
  `from app.storage import ...`, binding those names into its own namespace at
  import time.
- **`tests/fixtures/sample.kml`**: 12 real placemarks trimmed from a live
  export (only the photo tokens stubbed), each covering a specific parse shape
  — see the comment at the top of the file. 12 rather than 6 because
  `validate_structure` rejects >10% of rows missing hours and exactly one entry
  legitimately has no `営業時間` label; a smaller fixture trips the ratio and
  forces tests to fake the real validator away. Keep that proportion if you add
  to it.
- **`test_hours_golden.py` is the highest-value file.** `hours_parsed.json`
  carries `_raw_hours`/`_raw_holidays` beside each expected parse, so it doubles
  as a golden corpus: the rule tier must reproduce 113 of the 125 entries
  exactly and must still *fail* on exactly the 12 `CORRECTIONS` keys (a stale
  hand-fix is as much a bug as a regression). Also pins that every entry
  satisfies the frontend's `HoursJson` shape, and allowlists the 5 entries with
  a legitimate source-text hours gap so a *new* gap fails.
- **`test_db.py` asserts on `UPSERT_SQL` as a string**, because the one
  irreversible failure here is `stamp`/`badge` appearing in that query — a
  データ更新 would wipe collection state the source cannot regenerate. Found by
  checking which deliberate regressions the suite *fails* to catch; adding
  `stamp` to the column list passed everything before that file existed.
  It also pins the stamp-number invariant: `ON CONFLICT (id)`, `id` supplied
  explicitly, `name`/`lat`/`lon` present in `DO UPDATE SET`, ids assigned
  `1..N` from list order, and — end to end over `fixtures/sample.kml` —
  position N in the KML becoming id N in the upsert. Reverting `db.py` to the
  old natural key fails 9 of them.
- Not covered by choice: `app/auth.py`'s JWT verification (needs an RSA
  keypair + JWKS stub to test PyJWT doing its job), React components,
  `app/db.py` against a real Postgres, and `android/`.

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
