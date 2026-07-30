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

A magnifying glass in the top-left searches every location by name or by
stamp number — an all-digit query is treated as a number *prefix*, so typing
`1` matches 1, 10–19 and 100+, and `12` narrows it.

Five separate pieces:

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
- **Auth0** — Google login against a small email allowlist. Supabase trusts
  the tenant as a Third-Party Auth provider, so row-level security evaluates
  the real ID token; `pipeline/` verifies the same token independently. Not
  optional — nothing renders or reads data without it.

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

Run the schema once against your Supabase project
(`psql "$PIPELINE_DATABASE_URL" -f db/supabase_schema.sql`), **and** register
Auth0 as a Third-Party Auth provider (Supabase Dashboard → Authentication →
Third-Party Auth).

> On a project created before the `hours_json` / `display_json` columns
> existed, the `CREATE TABLE IF NOT EXISTS` above is a no-op and won't add
> them. Run the two `ALTER TABLE locations ADD COLUMN IF NOT EXISTS …` lines
> from `db/supabase_schema.sql` in the Supabase SQL Editor instead — don't
> paste the whole file, since `CREATE POLICY` has no `IF NOT EXISTS` and
> will error where the policies already exist. Neither column needs a grant
> or policy change: `GRANT SELECT` is table-wide and `GRANT UPDATE` stays
> scoped to `(stamp, badge)`.

Then start the service and trigger a pipeline run (needs a real Auth0 ID
token — easiest to copy one out of the frontend's network tab after logging
in):

```bash
cd pipeline
uvicorn app.main:app --port 8000    # or `make pipeline` from the repo root
curl -X POST http://localhost:8000/pipeline/run -H "Authorization: Bearer <id-token>"
```

Adding a pipeline-written column the frontend also *reads* is **four ordered
steps**, not one: `ALTER TABLE` in the SQL Editor → push the pipeline
change → run データ更新 to populate it → push the frontend change. The
frontend push is last because `render.yaml`'s web service has no
`buildFilter` and so redeploys on *every* push; ship it before the column is
populated and the panel renders its fallback.

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
npm run dev          # or `make web` from the repo root
npm run build        # production build
```

Working on the map alone needs nothing else running — `web/` reads Supabase
directly, so the `pipeline/` service is only required to refresh the data.

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

Parsing is three tiers, keyed by `sha1` of the raw text:

1. **`verified`** — a hand-reviewed entry in `pipeline/app/hours_parsed.json`.
2. **`manual`** — same file, for local knowledge the source does *not* state
   (currently one entry: a hotel with no `営業時間` label at all).
3. **`auto`** — the rule-based fallback, always available.

Tier one exists because the rule tier discards parentheticals as noise
(`（最終入園15:30）`, `(L.O.16:30)`) and so also discards the handful that
carry real hours. Anything falling back to the rule tier is counted and
reported in the データ更新 toast as `N件が未確認`, because that tier fails
confidently rather than loudly.

Because the key is content-addressed on the raw text, identical source text
dedupes — 136 locations collapse to 125 keys (seven hotels share
`年中無休`/`なし`), which is why each entry's `_names` is an array. A hash miss
never creates or breaks a DB row: the upsert key is `id`, and the hash only
indexes the override file. An upstream text edit *should* stop matching, since
a hand-written override must not keep overriding data that changed.

Sixteen of the 136 locations (12%) can't be fully determined — `不定休` means
"irregular holidays" and the schedule was simply never written down. That's
not a parser weakness; no parser extracts a schedule nobody wrote. Those
render honestly (no ring, or a ⚠ caveat) rather than guessing.

```bash
cd pipeline
python -m app.hours                    # review harness: every parse vs its raw text
python tools/gen_hours_overrides.py    # regenerate the override file after a KML change
```

Regenerating preserves existing entries, so hand corrections survive; only
new or upstream-edited entries get a fresh rule-based baseline. The
generator's `CORRECTIONS` dict carries the rationale for each hand-fix.
`python -m app.hours` fetches the **live** KML, so it's the tool for
eyeballing new upstream text — not a change gate; `make test` is (see
"Tests").

## Line breaking

Where the freeform Japanese wraps in the detail panel is decided in the
pipeline, not the frontend: `pipeline/app/display.py` writes a `display_json`
column holding pre-broken lines per field, plus the その他 partition. The
frontend just renders them (`web/src/data/displayLines.ts` is only the fallback
for a row the pipeline hasn't written yet).

Rules were tried and retired. Breaking is a *semantic* call — no rule knows
that `富士急沼津店` is a branch of モスバーガー while `やま弥` is the actual
name of 駿陽荘, and Japanese puts the descriptor before the name about as often
as after (`旅館 浜の家` vs `グランマ シーサイド店`), so ordering heuristics
don't help either. Four rounds of rules left ~9 cases unresolvable, failing
them confidently. So `pipeline/app/display_lines.json` is authored per entry
(152 of them) and **the git diff of that file is the review** — there is no
rule baseline to diff against.

Two tiers only, keyed on `sha1(field \x1f normalized_text)`: `verified`
(a committed entry) → `auto` (one line per author break, URLs isolated,
nothing else decided). Keys are **per field**, so editing a location's 営業時間
leaves its 定休日 lines alone and `なし` is reviewed once rather than 35 times.

Content leaves an entry by one of **three** destinations: `lines` (stays in its
own field), `extra` (→ その他: parking, URLs, phone numbers, stamp placement,
admission fees), or `to_holidays` (営業時間 → 定休日). The last exists because
three locations write their closure days into the 営業時間 text and carry no
定休日 label at all, so the panel used to show a 定休日 of `なし` directly above
営業時間 listing the very closures it denied.

### Editing `display_lines.json` by hand

An entry may only **move whitespace around and drop the commas it breaks on**.
That contract is `entry_problems()`, shared by the generator and the test
suite — the generator refuses to write what the test would reject, so a bad
stub shows up as a rising `unverified_lines` count in the データ更新 toast
rather than as a silently wrong `verified`. Two invariants do the work: every
line's non-droppable characters must be a contiguous run of the source's (no
reordering, no insertion), and the character multiset across all three
destinations must equal the source's after subtracting any declared
`_duplicate` (nothing lost, nothing accidentally duplicated).

So the loop for a hand edit is just:

```bash
# edit pipeline/app/display_lines.json directly, then:
make test-py    # entry_problems per entry; failure ids read field:name
```

No live KML, no database, no generator run — `test_display_golden.py` reads
the committed corpus, so this is the fast path and the actual gate. It
catches a dropped character, a paraphrase, an invented line, a within-line
reorder, undeclared duplication, a stale `_duplicate`, a hand-edited `_text`,
and a URL pulled inline. **A source typo must survive**: `土日祝 10:0～20:00`
is what the KML says — fix that upstream, not here.

To pick up genuinely new upstream text, regenerate (needs the live KML, so
network + GDAL):

```bash
cd pipeline
python tools/gen_display_overrides.py
```

Existing keys keep their committed entry; new keys get an auto-tier stub to
rewrite by hand. It unions `tests/fixtures/sample.kml`'s keys with the live
KML's — the fixture is the only offline source of real 住所 text, so building
from the live KML alone would let an upstream edit delete the entry the
address coverage check depends on. It prints `!!` for dropped or stale keys.
For new shapes worth reviewing, grep the corpus for `[（(]`.

## Tests

```bash
pip install -r pipeline/requirements-dev.txt   # pytest, once
make test                                      # both suites, ~2s
make test-py                                   # pytest for pipeline/ only
make test-web                                  # vitest for web/ only
```

`make test-py` is pytest over `pipeline/tests/`; `make test-web` is vitest over
`web/src/**/*.test.ts`. The `.ts`-only pattern is deliberate — `.tsx` goes
unmatched, so any logic worth testing lives in a plain module rather than
inside a component.

Both halves run **fully offline** — no network, no database. The KML is
`pipeline/tests/fixtures/sample.kml`, 12 real placemarks trimmed from a live
export with only the photo tokens stubbed, each covering a specific parse
shape. Twelve rather than six because `validate_structure` rejects a run with
more than 10% of rows missing hours and exactly one entry legitimately has no
`営業時間` label; a smaller fixture trips that ratio and forces tests to fake
the real validator away. `pipeline/tests/conftest.py` stubs out database access
entirely, since `PIPELINE_DATABASE_URL` normally points at production.

The weight sits on the places where a bug is a *wrong answer* rather than a
crash:

- **The hours parser** — `pipeline/app/hours_parsed.json` doubles as a golden
  corpus, storing each entry's raw source text beside its expected parse. The
  rule tier must reproduce 113 of the 125 committed entries exactly and must
  still *fail* on exactly the hand-corrected ones, so a stale correction is
  caught as readily as a regression.
- **The clock evaluation** that turns that output into a marker's ring —
  including the `Asia/Tokyo` resolution and the overnight (`end > 1440`)
  shifts.
- **The line-breaking corpus** — content preservation per entry, via
  `entry_problems` (see "Line breaking" above).
- **`stamp`/`badge` never appearing in the upsert.** `test_db.py` asserts on
  the SQL as a *string*, because that's the one irreversible failure here: a
  データ更新 that wipes collection state the source cannot regenerate. It was
  added after checking which deliberate regressions the suite failed to
  catch — adding `stamp` to the column list passed everything beforehand.

Not covered by choice: `pipeline/app/auth.py`'s JWT verification (would need an
RSA keypair and a JWKS stub to test PyJWT doing its job), React components,
`pipeline/app/db.py` against a real Postgres, and `android/`.

## Notes

- `pipeline`'s upsert (`pipeline/app/db.py`) is keyed on `id`, which is the
  placemark's 1-based position in the KML — that position is the stamp number
  shown on the marker, so it's data, not a surrogate key. It deliberately
  never touches the `stamp`/`badge` columns — those are collection state,
  written only by the frontend (`PATCH` straight to Supabase's REST API),
  never by the pipeline.
- `PIPELINE_DATABASE_URL` normally points at the live Supabase, so a
  locally-run `pipeline/` writes to production — there's no staging DB.
