# CLAUDE.md

Guidance for Claude Code working in this repo.

## What this is

Numazu (沼津) "machiaruki" stamp-rally map — Love Live! Sunshine!! stamp
locations from a public Google My Maps KML export. Five pieces:

1. **`web/`** — static React + Vite + Leaflet frontend. Numbered markers, two
   independent visual channels (fill = collection progress, ring = open/closed
   right now), tap-to-open centered detail panel (photo, member, address,
   hours, holidays, open-status badge, スタンプ/缶バッジ checkboxes), top-right
   filter panel. Reads Supabase's REST API (PostgREST) directly — no
   KML/pipeline logic here.
2. **`pipeline/`** — FastAPI service owning the pipeline: download KML →
   clean/parse → download photos → upsert Postgres + upload photos to Supabase
   Storage. Runs only on `POST /pipeline/run`.
3. **`android/`** — personal-sideload-only wrapper (not on Play), opens the
   deployed `web/` site fullscreen via Trusted Web Activity. See "Android app".
4. **Supabase** (Postgres + Storage) — `locations` table
   (`db/supabase_schema.sql`) + photo bucket.
5. **Auth0** — personal app, small email allowlist, Google login only.
   Supabase trusts that tenant as **Third-Party Auth** provider (Dashboard >
   Authentication > Third-Party Auth) → RLS evaluates the real ID token, not a
   static key; `pipeline/` verifies the same token independently against
   Auth0's JWKS. See "Auth".

`db/` + `postgrest/`: also a **local** Postgres + standalone PostgREST setup
(no Docker/Supabase CLI) for dev before Supabase — `db/schema.sql` vs
`db/supabase_schema.sql` (latter adds the RLS policies PostgREST expects;
local uses plain `GRANT`s).

## Environment & commands

- **`pipeline/`**: pyenv virtualenv `aqours` (`.python-version`), Python 3.10;
  `pip install -r pipeline/requirements.txt`. GDAL needs the native lib first
  (`sudo apt-get install libgdal-dev gdal-bin`); pinned `GDAL==` must match
  `gdal-config --version`. Run
  `cd pipeline && uvicorn app.main:app --port 8000`. Trigger needs a valid
  Auth0 ID token (see "Auth"):
  `curl -X POST http://localhost:8000/pipeline/run -H "Authorization: Bearer <token>"`.
  Credentials in `pipeline/.env` (gitignored); keys listed in README.md.
- **`web/`**: `cd web && npm install && npm run dev` (Vite, port 5173+);
  `npm run build` for prod. Credentials in `web/.env.local` (gitignored).
- **`android/`**: JDK 17 + Android SDK cmdline tools (`platform-tools`,
  `platforms;android-34`, `build-tools;34.0.0`) via
  `android/local.properties`'s `sdk.dir` (gitignored, machine-specific). Build
  `cd android && ./gradlew assembleDebug`; sideload
  `adb install -r app/build/outputs/apk/debug/app-debug.apk`. Keystore creds in
  `android/keystore.properties` (gitignored); README.md covers setup + wiring
  `web/public/.well-known/assetlinks.json`.
- **Tests**: `make test` = both suites (~2s, fully offline — no network, no
  DB). `make test-py` = `cd pipeline && python -m pytest`; `make test-web` =
  `cd web && npm test` (vitest). pytest needs
  `pip install -r pipeline/requirements-dev.txt` once — deliberately not in
  `requirements.txt`, keeps `pipeline/Dockerfile`'s image slim. Linting is just
  `tsc`/`oxlint` defaults in `web/`. See "Tests".
- **`PIPELINE_DATABASE_URL` in `pipeline/.env` points at live Supabase** — a
  locally-run pipeline writes production; no staging DB.
- Root `render.yaml`: two services, both auto-deploy on push.
  `aqours-machiaruki-pipeline` (`pipeline/Dockerfile`, Docker, free plan,
  `buildFilter` → `pipeline/**`); `aqours-machiaruki-web` (`runtime: static`,
  `rootDir: ./web`, `npm ci && npm run build`, no `buildFilter` → redeploys
  every push). Pipeline container stateless — everything persistent lives in
  Supabase. `envVars`: `sync: false` for secrets (set once in the dashboard),
  plain `value:` for the non-secret Auth0 domain/client ID (see "Auth").

## Development workflow

- `pipeline`/`web` dev servers on demand only, not proactively.
- Pipeline change → no need to re-trigger `/pipeline/run` unless
  KML-parsing/upsert logic changed; the frontend reads Supabase directly.
- Frontend changes verified manually by the user unless stated otherwise.
- Schema changes: apply the `ALTER TABLE ... IF NOT EXISTS` line in the
  Supabase SQL Editor **before** pushing pipeline code that writes the new
  column (Render auto-deploys on push). Never paste all of
  `db/supabase_schema.sql` — `CREATE POLICY` has no `IF NOT EXISTS`, errors
  wherever the policies already exist.

## Git commit conventions

- One feature/fix per commit, grouped by logical category; commit each
  separately, not as one large commit.
- Never `git reset`/`checkout`/`stash` to reconstruct cleaner category splits —
  work forward from the working tree as-is.
- A file's state spanning two categories → don't split its diff; current
  category wins, the earlier category's changes to that file roll in.

## Data pipeline (`pipeline/`)

1. **`app/kml.py`** — `fetch_kml()` downloads fresh every call.
   `os.environ['OGR_SKIP'] = 'LIBKML'` sits **at the top of the file, before
   the `geotable`/`osgeo` import**: forces GDAL's built-in KML driver over
   `LIBKML` (installed by `libgdal-dev`, otherwise preferred). Load-bearing —
   `geotable` hardcodes a drop-list deleting lowercase `description`; the
   built-in driver exposes it capitalized (`Description`), which survives and
   is what `description.py` expects. Remove it → image/address/hours/member
   parsing breaks silently, no error.
2. **`app/description.py`** — `parse_description()` reads each placemark's
   `Description` HTML (`<img>` + `メンバー／`/`住所／`/`営業時間／`/`定休日／`
   labels in a CDATA blob). Fields located **by string position**, not by fixed
   neighbours — some entries omit the member/hours label; missing → empty
   string/`'なし'`, never a raise. Touching this: recheck the label-less
   entries, not just the common case. Returns **both** the display strings
   (`hours`/`holidays`, cosmetically normalized) and the untouched
   `raw_hours`/`raw_holidays` — `app/hours.py` content-addresses the raw text,
   so normalizing first would make its hash depend on cosmetic choices here.
   `holidays` keeps **every** `<br>` line; the old `.split('<br>')[0]` silently
   dropped the `※閉店により、終了しました。` marker on the 8 closed shops.
3. **`app/images.py`** — `cache_images()` hashes each location's **natural
   key** (`name|lat|lon`, SHA1) as the Storage object key (`app/storage.py`),
   *not* the photo URL: Google embeds a per-request token in that URL, so it
   differs every fetch — keying on it meant the cache never hit and every run
   silently re-uploaded a duplicate of every photo. `object_exists()` first; on
   a miss, fetch from Google's `mymaps.usercontent.google.com` CDN
   (blocks/rate-limits repeats) and `upload_object()` (`x-upsert: true`).
   Storage *is* the dedupe cache — no local disk, since Render's free-plan
   container has none and a restart/redeploy would lose it. Frontend reads the
   `img_url` column (Storage public URL), not a local path.
4. **`app/validation.py`** — `validate_structure()` checks a fresh KML against
   the *previous* successful run's KML ("accepted structure" baseline) before
   any DB write: required columns present, every placemark has a name + Point
   geometry, count not dropped past `MIN_COUNT_RATIO` of baseline,
   address/image/hours extraction not broken past
   `MAX_EMPTY_ADDRESS_RATIO`/`MAX_EMPTY_IMG_RATIO`/`MAX_EMPTY_HOURS_RATIO`. The
   hours check guards *extraction* only — a run where many rows fall back to
   the rule-based tier is reported via `unverified`, never rejected. Raises
   `PipelineValidationError`; the run is a background task whose triggering
   request already returned, so `app/main.py` records `last_result: 'error'`
   for `GET /pipeline/status` (no HTTP error code), discards the download,
   DB/baseline untouched. First-ever run (no baseline): count-drop check
   skipped, rest still applies.
5. **`app/hours.py`** — `parse_hours_holidays()` turns the freeform Japanese
   `営業時間`/`定休日` into the `hours_json` column. See "Business hours".
6. **`app/db.py`** — `upsert_locations()` keys on **`id` = the placemark's
   1-based position in the KML**; that position *is* the stamp number the map
   renders (`MapView.tsx` labels each marker `loc.id`), so `id` is domain data,
   not a surrogate key. Derived from list order via
   `enumerate(records, start=1)`, never read off the record → `records` must
   arrive in KML order and be the complete set; `_build_records()` builds it
   straight from `placemarks.iterrows()`, which preserves document order. Never
   touches `stamp`/`badge` — absent from the `INSERT` columns (new rows default
   both `false`) and from `ON CONFLICT DO UPDATE SET` (existing rows keep
   state). The pipeline owns everything except collection state, which only the
   frontend writes — don't add `stamp`/`badge` to this query.
   `name`/`lat`/`lon` *are* in `DO UPDATE SET`: the row at position N must
   follow the KML if its text changes. `hours_json` goes through
   `psycopg2.extras.Json` at execute time, so callers hand over a plain dict.
   Returns `(inserted, updated)`, used by `app/main.py`.
   **Why not the old `(name, lat, lon)` natural key**: `name` isn't stable.
   Two placemarks carry a literal newline in `<name>` (`海鮮丼と魚河岸定食\nかもめ丸`,
   `ラブライブ！サンシャイン!!\nプレミアムショップ`) and one run emitted them
   space-joined instead. The natural key missed those rows and `INSERT`ed
   duplicates taking `nextval()` — by then in the 1400s, because
   `ON CONFLICT DO UPDATE` evaluates column defaults *before* detecting the
   conflict, so every run burned one sequence value per placemark even when it
   only updated. Result: phantom markers **1411** and **1478** beside the real
   51 and 118, collection state stranded on the originals. Position-keying
   fixes both halves — a rename updates the row in place, and supplying `id`
   explicitly never touches the sequence. The table's old
   `UNIQUE (name, lat, lon)` was dropped with it; on an unstable `name` it only
   stood to wedge future runs. Still uncovered: a location *leaving* the KML
   leaves a stale trailing row past the new count (nothing deletes rows;
   `validate_structure` only blocks a count drop past `MIN_COUNT_RATIO`).
7. **`app/main.py`** / **`app/pipeline_state.py`** — `POST /pipeline/run`:
   verify the Auth0 ID token (`app/auth.py`'s `verify_auth0_token`, see
   "Auth"), then a fast lock-protected check-and-kickoff returning
   `{'status': 'started'}` or `{'status': 'already_running'}` — never blocking
   for the full run. Work happens in FastAPI `BackgroundTasks`:
   `_run_pipeline()` does fetch/validate/cache/upsert and **raises**;
   `_execute_pipeline_run()` is a thin wrapper that only reports. Keep it that
   way — **every** path must call `pipeline_state.finish()` exactly once. An
   escaping exception leaves `running` set with nothing to clear it → every
   later trigger answers `already_running` until the container restarts, and
   the triggering request already returned 200, so nothing surfaces the wedge.
   (Regression: baseline download + final upload used to sit outside the
   `try`.)
   `pipeline_state`: in-memory
   `running`/`last_result`/`last_error`/`last_details` behind a
   `threading.Lock` (atomic across thread-pool handlers), unpersisted — a
   restart mid-run self-heals to "not running". `last_details` =
   `{inserted, updated, unverified}` on success; `unverified` counts rows whose
   schedule came from the rule tier rather than a hand-reviewed override,
   surfaced in `RefreshDataButton`'s toast. `GET /pipeline/status` exposes
   state for polling. A rejected/failed run still leaves DB/baseline untouched
   — only *when* the pipeline runs/reports changed, not validation/rollback
   semantics. Baseline KML in Supabase Storage, not local disk
   (`BASELINE_KML_KEY = '_pipeline/baseline.kml'`, same bucket); `tempfile` is
   scratch for `geotable.load()` only, nothing persists locally across
   requests.

## Business hours (`pipeline/app/hours.py` → `hours_json`)

Freeform Japanese `営業時間`/`定休日` → a structured schedule the frontend
evaluates against a clock. Against the live 136-placemark KML: 106 fully
determined by rules, 8 `年中無休`-only → 24h, 13 with `不定休`/`臨時休館`
closures, 8 permanently closed, 1 with no `営業時間` label at all. (The harness
reports `irregular: 16` — those 13 plus 3 the override file flags for
maintenance closures or an unstated end time.)

**The residual is not a parser weakness** — `不定休` means "irregular
holidays"; no parser, LLM included, extracts a schedule nobody wrote down. Goal
is *honest* status, not maximal coverage: `unknown` is a first-class outcome.

- **Three-tier lookup**, keyed by `sha1(raw_hours \x1f raw_holidays)[:16]`:
  `verified` (hand-reviewed entry in `app/hours_parsed.json`) → `manual` (same
  file; local knowledge the source does *not* state — currently only 三交イン
  沼津駅前, a hotel with no `営業時間` label) → `auto` (rule-based fallback,
  always available).
- **Why tier 1 exists**: the rule tier strips **all** parentheticals as noise
  (how it discards `（最終入園15:30）`/`(L.O.16:30)`), so it also discards real
  conditionals like `（木曜日は14:00まで）`. ~6 entries carry real hours inside
  brackets. Without the override, びゅうお shows a green ring at 16:00 on a
  Thursday when it shut at 14:00 — the rule tier fails *confidently*, not
  loudly. That's what `unverified` is for.
- **Content-addressed on the raw text**, so identical source text dedupes (136
  locations → 125 keys; 7 hotels share `年中無休`/`なし`) — hence `_names` is
  an array. An absent field still hashes fine, which keeps the 三交イン
  `manual` entry stable across runs.
- **A hash miss never creates a DB row.** Upsert key is `id` (KML position);
  the hash only indexes the override file. A miss (new location, or upstream
  text edited) recomputes `hours_json` from the rule tier and bumps
  `unverified`. An edited entry *should* stop matching — a hand-written
  override must not keep overriding changed source data.
- **Intervals are minutes from midnight** (`600` = 10:00). `11:00～26:00` →
  `[660, 1560]`; the frontend looks back a day for `end > 1440`, so 01:00 still
  reads as open.
- **Tokenize weekdays before anything else** (`_tokenize_days`). `日` is both
  "Sunday" and the suffix in `曜日`/`1月1日`, and compounds must be consumed
  whole — otherwise the `日` inside `平日`/`土日`/`日祝` is eaten as Sunday and
  `平日・土曜` parses as `平@sun・@sat`, silently losing all five weekdays.
  Single largest source of wrong parses.
- Other load-bearing details: parentheticals stripped **before** `※` notes
  (`平日（※祝日を除く）10:00~20:00` has a `※` inside the brackets; stripping to
  end-of-line first eats the range after them); day scope read as the text
  *between* consecutive time ranges, not by splitting on punctuation
  (`月・火・木・金・土7:00~13:00 日・祝日9:00~13:30` separates two scopes with
  only a space); `昼休み` ranges dropped, not added as opening hours.
- **Regenerate**: `cd pipeline && python tools/gen_hours_overrides.py`.
  Existing keys keep their committed entry so hand corrections survive; only
  new/changed keys get a fresh rule-based baseline. That script's `CORRECTIONS`
  dict holds the *rationale* per hand-fix.
- **Review harness**: `cd pipeline && python -m app.hours` prints every entry's
  parse beside its raw text and flags days with no hours that aren't a stated
  定休日. Fetches the **live** KML → the tool for eyeballing *new* upstream
  text, not a change gate. For that use `make test`:
  `tests/test_hours_golden.py` runs the same checks offline over the committed
  corpus, including the `!!` gap flag (see "Tests").

## Frontend (`web/src`)

- **`data/types.ts`** — `Location` mirrors the Postgres row exactly (incl.
  `stamp`/`badge`, `hours_json`); PostgREST returns all columns by default, no
  mapping layer. A `jsonb` column arrives as **real nested JSON**, so
  `hours_json.weekly.thu` is a live array — no parse step, no fetch change.
- **`data/supabaseRest.ts`** — shared `API_BASE`/`authHeaders()` for
  `useLocations` (GET) and `useToggleCollected` (PATCH); swapping Supabase
  projects is a two-env-var change here, not code. `authHeaders()` is `async`,
  sourcing `Authorization` from a live Auth0 ID token via a registered getter
  (`registerIdTokenGetter()`), not a static key. `apikey` still sends the
  static publishable key — Supabase's gateway needs it for routing regardless
  of auth method.
- **`auth/AuthGate.tsx`** — wraps the whole app (`main.tsx`, inside
  `Auth0Provider`); nothing renders behind it until Auth0 login succeeds
  (`loginWithRedirect` with `connection: 'google-oauth2'`, skips the
  account-chooser). An Auth0 Action denies all but the owner's email
  server-side, so it's a real gate, not just client-side. Once authenticated,
  `registerIdTokenGetter()` is called **synchronously during render**, not from
  a `useEffect` — React fires child effects before parent ones, so an effect
  here races `useLocations`' mount-time fetch and the first request goes out
  tokenless (401 under RLS). `<StrictMode>`'s double-invoke masks that in dev;
  prod builds don't.
- **`auth/freshIdToken.ts`** — the only place an ID token is obtained;
  `AuthGate` and `RefreshDataButton` both route through it, nothing calls
  `getIdTokenClaims()` directly. Auth0 SPA-JS caches the ID token with **no
  expiry**, and `getAccessTokenSilently()` only exchanges once the
  separately-cached *access* token goes stale (24h default vs the ID token's
  10h) → for a 14h window a day both read as fine while every request ships an
  expired ID token: `401 PGRST303 JWT expired` from Supabase, same rejection
  from `/pipeline/*`. Hence the explicit `exp` check + `cacheMode: 'off'`,
  skipped while the token is valid to keep Auth0 off the hot path. Pinned by
  `freshIdToken.test.ts`.
- **`panel/RefreshDataButton.tsx`** — the "データ更新" button; token from
  `getFreshIdToken()`, `POST`s the raw ID token to `VITE_PIPELINE_API_BASE`'s
  `/pipeline/run` (independently verified, see "Auth"). Returns almost
  immediately (`'started'`/`'already_running'` — backend runs the pipeline
  after, not inline), so the loading state covers only that round-trip; a
  `Toast` reports which, and `pollUntilDone()` (`GET /pipeline/status` ~3s)
  picks up the eventual result either way — success → toast +
  `window.location.reload()` after dismiss, error → error toast. A mount-time
  effect repeats the status check without a `POST`, so a run abandoned
  mid-flight (button clicked, page reloaded) still surfaces without another
  click.
- **`panel/Toast.tsx`** — small fixed-position, `user-select: none`
  bottom-center notification (blue/green/red), used only by
  `RefreshDataButton`; not a global toast system.
- **`data/markerColors.ts`** — single choke point for colour *and* filtering.
  `colorFor()` (blue/orange/grey by stamp+badge count) is the marker **fill**;
  `ringColorFor()` maps an `OpenStatus` to the **ring** (green open / amber
  closing within 2h / red closed / black permanently closed / `null` unknown →
  no ring). Two independent channels — don't fold open-status into the fill.
  `matchesFilters()` takes `now` and **AND**s its filters (was OR, until the
  panel went to one checkbox per *concept* rather than per *field*).
- **`data/openStatus.ts`** — `openStatusFor(hours_json, now)`, pure. Order
  matters: `permanently_closed` short-circuits before the clock (a shut shop is
  never "open"), then `always_open` (a 24h place must never read
  `closing_soon`), then closed-dates/closed-days/nth-week, then today's
  intervals, then yesterday's `end > 1440` overnight shifts. All dates resolved
  in **Asia/Tokyo** via `Intl.DateTimeFormat`, never the device timezone — the
  shops are in Numazu wherever the phone thinks it is. `@holiday-jp/holiday_jp`
  supplies 祝日 (incl. 振替休日 and the astronomical 春分/秋分), needed because
  the source text treats 祝日 as its own category (`土日祝`, `日曜日・祝日`);
  `isHoliday()` takes a `YYYY-MM-DD` string, sidestepping Date/timezone
  conversion entirely. ~13 kB gzipped.
- **`data/textLines.ts`** — `toDisplayLines()`, sole decider of where the
  freeform Japanese in `name`/`address`/`hours`/`holidays` breaks into lines.
  Pure → rules pinned offline (`textLines.test.ts`). **Deliberately not in the
  pipeline** despite those fields being parsed there: breaking is presentation,
  a pipeline change would need a データ更新 run against production to show up,
  and `app/hours.py` content-addresses `raw_hours`/`raw_holidays`. Each
  parenthetical is captured as its own `split()` group → **atomic** (a space or
  `、` inside never breaks — what stopped ほさか's `（6月～9月 10:00～20:00）`
  being cut in half by the whitespace rule), and an **unclosed** bracket goes
  unmatched, so unanticipated text survives whole rather than mangled. Rules:
  always break after `）` *unless* a non-comma symbol follows (`(不定休)・日`
  stays together); break before `（` only at **≥10 characters** inside, since a
  short qualifier like `（L.O.16:30）` reads as part of the time it follows; a
  comma *outside* brackets is **replaced by** a break, interior ones left
  alone. Those last two are why no line starts with orphaned punctuation.
  `breakOnWhitespace`: whitespace is how a source `<br>` arrives
  (`description.py` converts it) in the three fields, but a space in a `name`
  is just a space — pass `false` there or `三交イン 沼津駅前` splits in two.
- **`hooks/useLocations.ts`** — fetches once on mount; exposes `setLocations`
  for `useToggleCollected`'s optimistic updates, plus `refreshOne(id)`, a
  targeted `?id=eq.<id>&select=id,stamp,badge` fetch (not a full ~136-row
  re-fetch) called by `App.tsx` on detail-panel open, so cross-device
  `stamp`/`badge` changes pick up without a reload.
- **`hooks/useToggleCollected.ts`** — checkbox toggle updates local state
  optimistically, `PATCH`es Supabase, rolls back on failure. Tracks in-flight
  `(id, field)` pairs via a `ref`, not just `state`, avoiding a same-tick race,
  so a rapid double-click can't fire overlapping requests — `DetailPanel`
  disables + spinners a checkbox while its write is pending.
- **`map/MapView.tsx`** / **`map/markerIcon.ts`** — Leaflet markers are
  `L.divIcon` (colored circle + number), memoized on `[color, number, ring]`;
  the ring must be in the cache key or markers keep their first-rendered status
  forever. The ring is a `box-shadow`, not a `border`, so the disc keeps its
  full diameter and the number stays centred either way. No Leaflet `Popup` —
  `DetailPanel` is a plain fixed-position div, centered in the viewport rather
  than anchored to the tapped marker (mobile-friendly, no hover on touch).
- **`panel/Backdrop.tsx`** — dimmed full-screen div while the panel is open;
  tap closes it. Needed because marker clicks bubble to Leaflet's own map click
  handler — without it a tap opens then immediately closes the panel.
- **`hooks/useUserLocation.ts`** — browser Geolocation
  (`getCurrentPosition`, one-shot, not `watchPosition`). Denied/unsupported →
  no error, just no current-location marker.
- **`App.tsx`** — holds a `now` state ticking every 60s. **Load-bearing**:
  without it the `visibleLocations` memo and `markerIcon`'s module-level cache
  both freeze at page-load time, so rings and the `営業中のみ` filter would
  never update as the clock advances. `now` is threaded to `MapView`,
  `DetailPanel`, and the filter memo's deps.
- **`panel/FilterPanel.tsx`** — exactly two flat checkboxes, `未獲得`
  (`!stamp || !badge`) and `営業中のみ` (status `open` or `closing_soon`), no
  group headers; they **stack (AND)**. `App.tsx`'s `FILTER_KEYS` validates
  stored keys, so the pre-existing `['stamp_missing','badge_missing']`
  localStorage value is silently dropped on load — no migration code needed.
- **`panel/DetailPanel.tsx`** — `StatusBadge` renders the computed status
  directly **above** the raw Japanese it came from, so a bad parse shows up in
  ordinary use, not only when someone goes looking. `irregular` notes → ⚠
  caveat lines; `permanently_closed` → struck-through grey title.
  住所/営業時間/定休日 each sit behind a `CollapsibleField`, **collapsed on
  open**, expanding independently — photo, name and status badge have to fit a
  phone screen without scrolling, and one 営業時間 (歴史民俗資料館) runs nine
  lines by itself. Each field owns its `useState`; the three sit under a
  wrapper **keyed on `location.id`**, because tapping a second marker leaves
  this panel mounted and without the key a field stays expanded from the
  previous location. Header is a full-width flex row → whole line is the tap
  target (one-handed use while walking), not just the label. Bodies and ⚠ notes
  carry `textAlign: 'left'` + a 10px gutter against `PANEL_STYLE`'s centered
  default. Field values and the name go through `toDisplayLines`, the name with
  `breakOnWhitespace: false`; the address's Maps link still queries the
  untouched string, breaking being for reading only.
- Leaflet's zoom control defaults top-left → filter panel sits top-right
  (`FilterPanel.tsx`) to avoid overlap.

## Tests

`make test` → `pipeline/tests/` (pytest) + vitest over `src/**/*.test.ts`
(`web/vitest.config.ts`, so `src/data` and `src/auth` alike). Both fully
offline: verified to pass with `socket.connect` blocked and with
`pipeline/.env` renamed away. ~2s total — a per-change gate, not a CI ritual.

- **The suite must never reach production.** `PIPELINE_DATABASE_URL` points at
  live Supabase and there's no staging DB, so `tests/conftest.py` stubs
  `psycopg2.connect` to raise for every test (autouse fixture) and sets dummy
  env vars. **`load_dotenv()` doesn't override already-set vars** — that's what
  makes conftest's values win over the real `pipeline/.env`.
- **`conftest.py`'s import order is load-bearing.** Env vars set at module top
  *before* any `app.*` import (`app/auth.py` reads three with bare
  `os.environ[...]` at module level), then `import app.kml` *before* anything
  can pull in geotable/osgeo, so its `OGR_SKIP` write lands before GDAL locks
  in a driver.
- **`TestClient` runs `BackgroundTasks` synchronously** before returning the
  response — a `POST /pipeline/run` test that doesn't monkeypatch
  `app.main._execute_pipeline_run` runs the real pipeline against production.
- **Patch `app.images.*`, not `app.storage.*`** — `app/images.py` does
  `from app.storage import ...`, binding those names into its own namespace at
  import time.
- **`tests/fixtures/sample.kml`** — 12 real placemarks trimmed from a live
  export (only photo tokens stubbed), each covering a specific parse shape; see
  the comment at the top of the file. 12 rather than 6 because
  `validate_structure` rejects >10% of rows missing hours and exactly one entry
  legitimately has no `営業時間` label — a smaller fixture trips the ratio and
  forces tests to fake the real validator away. Keep that proportion.
- **`test_hours_golden.py` is the highest-value file.** `hours_parsed.json`
  carries `_raw_hours`/`_raw_holidays` beside each expected parse, so it
  doubles as a golden corpus: the rule tier must reproduce 113 of the 125
  entries exactly and must still *fail* on exactly the 12 `CORRECTIONS` keys (a
  stale hand-fix is as much a bug as a regression). Also pins every entry
  against the frontend's `HoursJson` shape, and allowlists the 5 entries with a
  legitimate source-text hours gap so a *new* gap fails.
- **`textLines.test.ts` runs on real corpus strings**, lifted from
  `hours_parsed.json`'s `_raw_hours`/`_raw_holidays` (post `<br>`→space, the
  form the panel receives) rather than invented — the ≥10-character threshold
  only earns its keep at the boundary: `最終入館16:00` and `土日祝は15:00` are
  9 and stay inline, `土曜日・日曜日を除く` is exactly 10 and breaks. Also pins
  `・` after `）` suppressing a break where `、` and a digit don't, an unclosed
  bracket coming back untouched, and ほさか's parenthetical no longer splitting
  mid-bracket. For new shapes, grep that file for `[（(]` — 20 of the 125
  entries carry parentheses.
- **`test_db.py` asserts on `UPSERT_SQL` as a string** — the one irreversible
  failure here is `stamp`/`badge` appearing in that query, where a データ更新
  would wipe collection state the source cannot regenerate. Found by checking
  which deliberate regressions the suite *failed* to catch: adding `stamp` to
  the column list passed everything before that file existed. Also pins the
  stamp-number invariant — `ON CONFLICT (id)`, explicit `id`,
  `name`/`lat`/`lon` in `DO UPDATE SET`, ids `1..N` from list order, and end to
  end over `fixtures/sample.kml`, position N becoming id N. Reverting `db.py`
  to the old natural key fails 9 of them.
- Not covered by choice: `app/auth.py`'s JWT verification (needs an RSA keypair
  + JWKS stub to test PyJWT doing its job), React components, `app/db.py`
  against a real Postgres, `android/`.

## Android app (`android/`)

Personal-sideload-only wrapper (`com.aqoursmachiaruki.app`, not on Play); only
job is opening the deployed `web/` site fullscreen. Standalone Gradle/Kotlin
project, unrelated to the `web/`/`pipeline/` toolchains.

- **Why TWA, not `WebView`**: the site gates everything behind Auth0 → Google
  login, and Google blocks OAuth sign-in inside embedded `WebView`s, so a raw
  `WebView` wrapper sticks at login. A Trusted Web Activity hosts real Chrome
  under the hood — same as the browser, just no toolbar — so OAuth works
  normally.
- **`MainActivity.kt`** launches the TWA via `TwaLauncher`
  (`androidbrowserhelper`), which pushes the browser activity onto the **same
  task** as `MainActivity`. Two gotchas, confirmed via `adb logcat`, not just
  theorized:
  - Must **not** `finish()` right after launching — races the browser activity
    still attaching, aborts the load/crashes on cleanup. `MainActivity` stays
    alive underneath, finishing only in `onRestart()` (user backs out of the
    browser, control returns) — mirrors Google's reference
    `androidbrowserhelper` `LauncherActivity`.
  - Icon rotation only in `onDestroy()`, never right after launch. Disabling
    the `activity-alias` that launched the *current* task closes that whole
    task immediately — `MainActivity` plus the TWA/Custom Tab on top — despite
    `DONT_KILL_APP` (protects the process only, not the task/activity stack).
    Rotating earlier silently kills the site mid-load.
- **Icon rotation** — nine `activity-alias` entries in `AndroidManifest.xml`
  (one per Aqours member, `res/mipmap-xxxhdpi/ic_launcher_<name>.png`), all
  targeting `MainActivity`, exactly one enabled at a time; `rotateIcon()`
  (from `onDestroy()`) picks a different one at random via
  `PackageManager.setComponentEnabledSetting`. The home-screen icon catches up
  only next time that launcher redraws — some launchers cache/lag a few opens
  behind actual state; a launcher quirk, not a rotation bug.
- **Fullscreen (no Custom Tab toolbar) needs domain verification** —
  `web/public/.well-known/assetlinks.json` declares the package name + signing
  cert SHA-256 fingerprint. Chrome checks it at runtime and falls back to a
  normal Custom Tab if verification fails/goes stale; degrades gracefully.
- Signed with a **dedicated keystore** (`android/keystore/release.jks`,
  gitignored), not the machine-local debug keystore, so the `assetlinks.json`
  fingerprint stays valid across machines/reinstalls. Creds in
  `android/keystore.properties` (gitignored, same pattern as
  `pipeline/.env`/`web/.env.local`); `app/build.gradle.kts` signs **both**
  debug and release with it.
- `androidx.browser` pinned to `1.8.0`, `androidbrowserhelper` to `2.5.0`
  deliberately — newer releases pull transitive deps requiring `compileSdk 36`+
  / AGP 8.9+, which this project doesn't use.

## Auth (Auth0 + Supabase)

Personal app, small email allowlist — only those emails can ever read/write
data, enforced at the data layer, not just client-side. Addresses stay out of
the repo: `pipeline/app/auth.py` reads `ALLOWED_EMAILS` (comma-separated,
`pipeline/.env` locally / `sync: false` in `render.yaml`), and the Auth0 Action
(dashboard-only, not in repo) enforces the same allowlist independently.

- **Auth0** authenticates via Google login (`google-oauth2`). An Auth0 Action
  (`onExecutePostLogin`, dashboard, not in repo) denies login outright outside
  the allowlist and stamps `role: 'authenticated'` onto the **ID token** —
  Auth0 strips unnamespaced custom claims from *access* tokens, which is why
  the ID token is what's passed around everywhere here.
- **Supabase** is a Third-Party Auth provider trusting that Auth0 tenant
  directly (Dashboard > Authentication > Third-Party Auth, external to repo):
  PostgREST verifies the ID token against Auth0's JWKS and assigns the
  `authenticated` Postgres role from the `role` claim.
  `db/supabase_schema.sql`'s RLS policies/grants are `TO authenticated` only —
  `anon` gets nothing, a deliberate change from the old fully-permissive model.
- **`pipeline/app/auth.py`** verifies the same ID token independently for
  `POST /pipeline/run` (`PyJWKClient` against Auth0's JWKS; checks
  signature/issuer/audience/email) — unrelated to Supabase's Third-Party Auth
  trust, the two just happen to trust the same tenant. Deliberately **not** a
  static shared secret: the "データ更新" button calls this endpoint straight
  from the browser, and anything baked into the Vite bundle (`VITE_*`) is
  effectively public once loaded.
- `web/`'s `VITE_AUTH0_DOMAIN`/`VITE_AUTH0_CLIENT_ID` and `pipeline/`'s
  `AUTH0_DOMAIN`/`AUTH0_CLIENT_ID` are **not secrets** — meant to be public in
  an SPA bundle — so plain `value:` in `render.yaml`, not `sync: false`.
- `useRefreshTokens` + `cacheLocation: 'localstorage'` (`main.tsx`'s
  `Auth0Provider`) avoid Auth0's legacy iframe silent-auth, increasingly broken
  by third-party-cookie blocking (Safari/Chrome) — matters for real
  walking-around-Numazu phone sessions, not just desktop. `useRefreshTokens` is
  also what `auth/freshIdToken.ts` needs to re-mint an expired ID token.
- Every token this app sends anywhere is the **ID** token, but auth0-spa-js's
  cache only tracks *access* token expiry — `auth/freshIdToken.ts` watches the
  ID token's own `exp`. Don't fix a 401 here by raising the ID token lifetime
  in the Auth0 dashboard; that only moves the window.
- `pipeline/`'s CORS (`app/main.py`) is scoped to the real frontend origin(s),
  not `allow_origins=['*']` — cross-origin requests carry an `Authorization`
  header, so a wildcard origin isn't appropriate.

## Supabase-specific notes

- API key naming: the dashboard calls the `anon` key the **publishable key**,
  the `service_role` key the **secret key**. `pipeline/` uses the secret key
  (Storage uploads); `web/` uses the publishable key only for the `apikey`
  header (routing, not identity — see "Auth").
- Local Postgres (`db/schema.sql`) skips RLS entirely (plain `GRANT`s to
  `web_anon`), unaffected by any of the above — dev-only scaffolding, never
  deployed, no Auth0 involved.
