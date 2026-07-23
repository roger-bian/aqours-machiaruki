# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-page Dash app (`app.py`) that plots a Numazu (沼津) "machiaruki" stamp-rally
map: Love Live! Sunshine!! character stamp locations pulled from a public Google
My Maps KML export, rendered as a Plotly Mapbox scatter plot with a custom hover
tooltip (photo, member, address, hours, holidays) per point, plus a marker for the
viewer's own IP-geolocated position.

## Environment & commands

- Python env is pyenv-managed, venv name `aqours` (see `.python-version`), Python 3.10.
- Install deps: `pip install -r requirements.txt`. The `GDAL` package requires the
  native GDAL library/headers first: `sudo apt-get install libgdal-dev gdal-bin`.
  The pinned `GDAL==` version in `requirements.txt` **must match** `gdal-config --version`
  on the system, or the pip install fails to build — re-pin and re-check after any
  GDAL system package upgrade.
- Run the app: `python app.py` — starts the Dash dev server at http://127.0.0.1:8050/,
  with debug mode and hot-reload already on (`app.run(debug=True)`).
- No test suite, linter, or build step exists in this repo.
- `nb/nb.ipynb` is a scratch/reference notebook documenting the original data
  exploration (KML download link, an earlier version of the cleaning logic, a
  `px.scatter_mapbox` + `hovertemplate` prototype). It's not run as part of the
  app and may drift out of sync with `app.py` — treat it as historical reference,
  not source of truth.

## Development workflow

- At the start of a session, start `python app.py` in the background and open
  http://127.0.0.1:8050/ in the browser via the Claude in Chrome extension.
  Leave it running for the rest of the session rather than restarting per change.
- After any code change, verify it using the Claude in Chrome extension (hover
  points, check the console/network tabs, screenshot as needed) instead of only
  checking the terminal — debug mode's hot-reload means most changes apply
  without a manual restart. This also keeps the same live page open so the user
  can watch changes happen in their own browser in real time.

## Data pipeline (the part that needs multi-file context)

1. **`fetch_kml()`** downloads the KML export from a Google My Maps link
   (`KML_URL`, a fixed `mid`/`lid` map ID) to `assets/machiaruki.kml` on first
   run only — it's a cache, not re-fetched if the file already exists. Delete
   the file to force a refresh. `assets/machiaruki.kml` is gitignored.
2. GDAL/OGR driver choice matters: `os.environ['OGR_SKIP'] = 'LIBKML'` is set
   **before** importing `geotable`/`osgeo`, forcing GDAL's built-in `KML` driver
   instead of `LIBKML` (which system `libgdal-dev` installs and GDAL otherwise
   prefers). This is load-bearing: `geotable` hardcodes a drop-list
   (`KML_COLUMNS` in the installed `geotable` package) that deletes the
   lowercase `description` field LIBKML produces; the built-in driver instead
   exposes it capitalized (`Description`), which survives and is what
   `df_clean()` expects. Removing the `OGR_SKIP` line silently breaks image/
   address/hours/member parsing with no error (the column just won't exist,
   or geotable will drop it) — don't "clean up" that line without re-verifying
   this behavior against the installed GDAL/geotable versions.
3. **`df_clean()`** parses each placemark's `Description` HTML field (an
   `<img>` tag + `メンバー／`/`住所／`/`営業時間／`/`定休日／` labels in a CDATA
   blob) via `_parse_description()`. Fields are located **by string position**,
   not assumed adjacent to fixed neighbors — the live map has grown over time
   (117 → 136+ locations) and newer entries sometimes omit the member or hours
   label entirely. Missing fields degrade to empty string/`'なし'` rather than
   raising; `display_hover()` correspondingly guards the member-color lookup
   with `.get(member, "black")` and skips the member `<P>` when blank. If you
   touch this parsing, re-check against entries missing labels, not just the
   common case.
4. **`cache_images()`** downloads each store photo (originally hosted on
   Google's `mymaps.usercontent.google.com` CDN) once, hashed by URL, into
   `assets/img/` (gitignored), and rewrites the `img` column to local
   `/assets/img/<hash>.<ext>` paths served by Dash's built-in static folder.
   This exists because that CDN blocks/rate-limits image requests made from
   an actual browser tab (confirmed via browser network inspection — plain
   `curl`/`requests` succeed, but the same URL fetched via `<img>`/`fetch()`
   from a page gets a 503). Do not point the tooltip's `img` src back at the
   original Google CDN URLs directly — self-hosting is required regardless of
   frontend framework.
5. The cleaned `t_clean` DataFrame feeds a single module-level `px.scatter_mapbox`
   figure; `display_hover()` (a Dash callback on `hoverData`) looks up the
   hovered point by `pointNumber` directly into `t_clean.iloc[num]` — row order
   in `t_clean` must stay aligned with the plotted trace's point order.
