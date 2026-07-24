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
  pipeline: `curl -X POST http://localhost:8000/pipeline/run`. Credentials
  (Supabase pooler connection string, secret key, bucket name) live in
  `pipeline/.env` (gitignored) — see README.md for the exact keys.
- **`web/`**: `cd web && npm install && npm run dev` (Vite dev server,
  default port 5173+). `npm run build` for a static production build.
  Credentials (Supabase project URL, publishable key) live in
  `web/.env.local` (gitignored).
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
6. **`app/main.py`**: `POST /pipeline/run` ties the above together and
   returns `{processed, inserted, updated}` (or a 422/502 error if
   validation/processing failed, in which case nothing is written). Not
   called automatically — trigger it manually (or via cron/webhook)
   whenever the source KML changes. The baseline KML used by
   `validate_structure()` is itself stored in Supabase Storage
   (`BASELINE_KML_KEY = '_pipeline/baseline.kml'`, same bucket as photos)
   rather than on local disk, and is only overwritten with the new
   download *after* validation and the DB upsert both succeed — a rejected
   or failed run leaves the baseline untouched. Local temp files
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

## Supabase-specific notes

- Auth model: no user accounts — `anon`/publishable-key access is
  permissive, scoped down at the **column** level instead of via row
  ownership: `GRANT SELECT` on the whole table, but
  `GRANT UPDATE (stamp, badge)` only. Confirmed via curl: the publishable
  key can `PATCH` `stamp`/`badge` but gets `permission denied for table
  locations` trying to change `name` or anything else — don't widen this
  grant without a reason.
- RLS is enabled on Supabase (`db/supabase_schema.sql`) with permissive
  `USING (true)` policies for both `SELECT` and `UPDATE` — the column
  grant is the actual security boundary here, not RLS. The local Postgres
  setup (`db/schema.sql`) skips RLS entirely (plain `GRANT`s), since
  standalone PostgREST doesn't need it the way Supabase's dashboard linter
  expects it.
- API key naming: Supabase's dashboard calls the `anon` key the
  **publishable key**, and the `service_role` key the **secret key**.
  `pipeline/` uses the secret key (Storage uploads); `web/` uses the
  publishable key (reads + the scoped `stamp`/`badge` updates).
