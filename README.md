# lovelive-machiaruki

## Setup

This project uses a pyenv-managed virtualenv named `aqours` (see `.python-version`).

```bash
pyenv install 3.10.20        # if not already installed
pyenv virtualenv 3.10.20 aqours  # if the venv doesn't exist yet
pip install -r requirements.txt
```

Note: the `GDAL` package requires the native GDAL library/headers to be installed
on the system first (`sudo apt-get install libgdal-dev gdal-bin`), and the pinned
`GDAL` version in `requirements.txt` must match `gdal-config --version`.

## Running locally

```bash
python app.py
```

This starts the Dash dev server at http://127.0.0.1:8050/. On first run, `app.py`
downloads `machiaruki.kml` (the store location data) and each location's photo
into `assets/`, caching them there; delete the files to force a re-download.

Debug mode and hot-reload-on-change are already enabled by default via
`app.run(debug=True)` in `app.py` — just edit and save a file and the app will
reload automatically. To disable, change `debug=True` to `debug=False`.
