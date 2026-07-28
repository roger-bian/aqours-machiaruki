import tempfile

from dotenv import load_dotenv

# must run before importing app.db/app.storage, which read connection
# details from the environment at module-import time
load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import pipeline_state
from app.auth import verify_auth0_token
from app.db import upsert_locations
from app.description import extract_img_url, parse_description
from app.hours import parse_hours_holidays
from app.images import cache_images
from app.kml import fetch_kml, load_placemarks
from app.storage import download_object, upload_object
from app.validation import PipelineValidationError, validate_structure

# the last validated KML, kept in the same Storage bucket as photos (not on
# local disk - Render's free plan has no persistent disk, so anything that
# must survive a restart/redeploy has to live in Supabase) - this is the
# "accepted structure" a fresh download is validated against
BASELINE_KML_KEY = '_pipeline/baseline.kml'
KML_CONTENT_TYPE = 'application/vnd.google-earth.kml+xml'

app = FastAPI(title='machiaruki-pipeline')

# the frontend now sends a real Authorization header (Auth0 ID token) on
# cross-origin requests, so a wildcard origin is no longer appropriate
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'https://aqours-machiaruki-web.onrender.com',
        'http://localhost:5173',
    ],
    allow_methods=['*'],
    allow_headers=['*'],
)


def _build_records(placemarks):
    records = []
    for _, row in placemarks.iterrows():
        description = row['Description']
        fields = parse_description(description)
        img_url = extract_img_url(description)
        records.append({
            'name': row['Name'],
            'lat': row.geometry_object.y,
            'lon': row.geometry_object.x,
            'member': fields['member'],
            'address': fields['address'],
            'hours': fields['hours'],
            'holidays': fields['holidays'],
            'hours_json': parse_hours_holidays(
                fields['raw_hours'], fields['raw_holidays']),
            '_raw_img_url': img_url,
        })
    return records


def _baseline_count():
    """Placemark count of the last validated KML, or 0 if there isn't one yet
    (the first-ever run). geotable.load() only takes a path, so the bytes from
    Storage have to go through a temp file."""
    baseline_bytes = download_object(BASELINE_KML_KEY)
    if baseline_bytes is None:
        return 0
    with tempfile.NamedTemporaryFile(suffix='.kml') as baseline_tmp:
        baseline_tmp.write(baseline_bytes)
        baseline_tmp.flush()
        return len(load_placemarks(baseline_tmp.name))


def _run_pipeline():
    """The actual fetch/validate/cache/upsert cycle. Returns the row counts for
    a successful run and raises on anything else - reporting is the caller's
    job, so that every outcome funnels through one place."""
    baseline_count = _baseline_count()

    with tempfile.NamedTemporaryFile(suffix='.kml') as new_tmp:
        fetch_kml(new_tmp.name)
        with open(new_tmp.name, 'rb') as f:
            new_kml_bytes = f.read()
        placemarks = load_placemarks(new_tmp.name)
        records = _build_records(placemarks)
        fields_by_row = [
            {
                'address': r['address'],
                'img_url': r['_raw_img_url'],
                'hours': r['hours'],
            }
            for r in records
        ]
        validate_structure(placemarks, baseline_count, fields_by_row)

        img_urls = cache_images(records)
        for record, img_url in zip(records, img_urls):
            record['img_url'] = img_url
            del record['_raw_img_url']

        inserted, updated = upsert_locations(records)
        # rows the committed overrides didn't cover, so their schedule came
        # from the rule-based tier and hasn't been eyeballed by a human -
        # surfaced in the frontend toast so the gap is pulled, not remembered
        unverified = sum(
            1 for r in records if r['hours_json'].get('confidence') == 'auto')

    # only now, having successfully validated and upserted, does the new
    # download replace the accepted-structure baseline for the next run
    upload_object(BASELINE_KML_KEY, new_kml_bytes, KML_CONTENT_TYPE)
    return {'inserted': inserted, 'updated': updated, 'unverified': unverified}


def _execute_pipeline_run():
    """Runs the full cycle and reports the outcome. Called via BackgroundTasks -
    nothing is waiting on a return value here (the triggering request already got
    its response), so failures update pipeline_state instead of raising an
    HTTP-flavored exception.

    Every path through this function must call finish() exactly once. An escaping
    exception would leave pipeline_state's `running` flag set with nothing left to
    clear it, so every later POST /pipeline/run answers 'already_running' until
    the process restarts - which is why the whole body is wrapped rather than
    just the parts that were expected to fail.

    One consequence worth knowing: if the Storage upload that promotes the new
    baseline fails after the upsert succeeded, this reports an error even though
    the data is live. The next run then validates against the older baseline,
    which is the conservative direction, and the operator should hear about it.
    """
    try:
        details = _run_pipeline()
    except PipelineValidationError as e:
        pipeline_state.finish('error', f'KML structure validation failed: {e}')
    except Exception as e:
        pipeline_state.finish('error', f'pipeline processing error: {e}')
    else:
        pipeline_state.finish('success', details=details)


@app.post('/pipeline/run')
def trigger_pipeline_run(background_tasks: BackgroundTasks, _: None = Depends(verify_auth0_token)):
    if not pipeline_state.try_start():
        return {'status': 'already_running'}
    background_tasks.add_task(_execute_pipeline_run)
    return {'status': 'started'}


@app.get('/pipeline/status')
def pipeline_status(_: None = Depends(verify_auth0_token)):
    return pipeline_state.snapshot()


@app.get('/health')
def health():
    return {'status': 'ok'}
