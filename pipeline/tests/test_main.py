"""Tests for app/main.py - the routes and the pipeline orchestration.

Two hazards to know about when reading these:

- `TestClient` executes FastAPI BackgroundTasks synchronously, before returning
  the response. Any route test that does not patch `app.main._execute_pipeline_run`
  therefore runs the *real* pipeline, against the live KML and production
  Supabase. Every POST test below patches it.
- The orchestration tests fake only the I/O seams (Storage, the download, the
  upsert) and let the real parsing and validation run over
  tests/fixtures/sample.kml, so they cover the wiring rather than re-testing the
  parsers.
"""
import pytest
from fastapi.testclient import TestClient

from app import display, hours, main, pipeline_state
from app.auth import verify_auth0_token
from app.validation import PipelineValidationError


@pytest.fixture
def client():
    main.app.dependency_overrides[verify_auth0_token] = lambda: None
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client():
    return TestClient(main.app)


@pytest.fixture
def fake_io(monkeypatch, sample_kml):
    """Replace every network/database seam in a pipeline run and record the
    calls. Parsing, hours resolution and validation stay real."""
    calls = {'uploaded': [], 'upserted': [], 'baseline': None}

    def fake_fetch_kml(path, url=None):
        with open(sample_kml, 'rb') as source, open(path, 'wb') as target:
            target.write(source.read())
        return path

    def fake_upsert(records):
        calls['upserted'].append(records)
        return len(records), 0

    monkeypatch.setattr(main, 'download_object', lambda key: calls['baseline'])
    monkeypatch.setattr(main, 'fetch_kml', fake_fetch_kml)
    monkeypatch.setattr(main, 'cache_images',
                        lambda records: [f"https://storage/{r['name']}" for r in records])
    monkeypatch.setattr(main, 'upsert_locations', fake_upsert)
    monkeypatch.setattr(main, 'upload_object',
                        lambda key, content, ct: calls['uploaded'].append((key, content, ct)))
    return calls


# --- routes ----------------------------------------------------------------

def test_health_needs_no_authentication(unauthenticated_client):
    response = unauthenticated_client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_run_requires_a_bearer_token(unauthenticated_client):
    """The button that calls this endpoint runs in the browser, so the endpoint
    cannot rely on a shared secret - anything in the Vite bundle is public."""
    assert unauthenticated_client.post('/pipeline/run').status_code == 401
    assert unauthenticated_client.post(
        '/pipeline/run', headers={'Authorization': 'Basic nope'}).status_code == 401


def test_status_requires_a_bearer_token(unauthenticated_client):
    assert unauthenticated_client.get('/pipeline/status').status_code == 401


def test_run_returns_immediately_and_queues_the_work(client, monkeypatch):
    """The response must not wait for the full run; RefreshDataButton's loading
    state only covers this round-trip and a status poll picks up the result."""
    ran = []
    monkeypatch.setattr(main, '_execute_pipeline_run', lambda: ran.append(True))

    response = client.post('/pipeline/run')

    assert response.status_code == 200
    assert response.json() == {'status': 'started'}
    assert ran == [True]


def test_second_run_is_refused_while_one_is_in_flight(client, monkeypatch):
    ran = []
    monkeypatch.setattr(main, '_execute_pipeline_run', lambda: ran.append(True))
    pipeline_state.try_start()

    response = client.post('/pipeline/run')

    assert response.json() == {'status': 'already_running'}
    assert ran == []


def test_status_exposes_the_last_run(client):
    pipeline_state.finish('success', details={
        'inserted': 1, 'updated': 2, 'unverified': 0, 'unverified_lines': 0})
    assert client.get('/pipeline/status').json() == {
        'running': False,
        'last_result': 'success',
        'last_error': None,
        'last_details': {'inserted': 1, 'updated': 2, 'unverified': 0,
                         'unverified_lines': 0},
    }


# --- record building -------------------------------------------------------

def test_build_records_maps_the_columns(placemarks):
    records = main._build_records(placemarks)
    assert len(records) == 12

    gamers = next(r for r in records if r['name'] == 'ゲーマーズ沼津店')
    # lat comes from geometry_object.y and lon from .x - easy to invert, and
    # inverting them would put every marker in the Indian Ocean
    assert gamers['lat'] == pytest.approx(35.10157)
    assert gamers['lon'] == pytest.approx(138.856807)
    assert gamers['member'] == '津島善子'
    assert gamers['address'] == '沼津市添地町72青秀ビル1階'
    assert gamers['hours_json']['weekly']['mon'] == [[660, 1200]]
    assert gamers['_raw_img_url'].startswith('https://mymaps.usercontent.google.com/')


def test_build_records_carries_the_permanently_closed_flag(placemarks):
    """The frontend strikes the title through and paints a black ring off this;
    it comes from a sentence on a later <br> line of 定休日."""
    records = main._build_records(placemarks)
    marusan = next(r for r in records if r['name'] == 'マルサン書店')
    assert marusan['hours_json']['permanently_closed'] is True


def test_build_records_never_includes_collection_state(placemarks):
    """stamp/badge belong to the frontend alone; the upsert must not carry them
    or a data refresh would wipe the user's collection."""
    for record in main._build_records(placemarks):
        assert 'stamp' not in record
        assert 'badge' not in record


# --- a successful run ------------------------------------------------------

def test_successful_run_upserts_and_promotes_the_baseline(fake_io):
    main._execute_pipeline_run()

    snapshot = pipeline_state.snapshot()
    assert snapshot['running'] is False
    assert snapshot['last_result'] == 'success', snapshot['last_error']
    assert snapshot['last_details'] == {
        'inserted': 12, 'updated': 0, 'unverified': 0, 'unverified_lines': 0}

    # the new download becomes the accepted-structure baseline only now, after a
    # successful validate + upsert
    key, content, content_type = fake_io['uploaded'][0]
    assert key == main.BASELINE_KML_KEY
    assert content_type == main.KML_CONTENT_TYPE
    assert b'<Placemark>' in content


def test_successful_run_swaps_the_raw_image_url_for_the_storage_one(fake_io):
    main._execute_pipeline_run()

    records = fake_io['upserted'][0]
    for record in records:
        assert record['img_url'] == f"https://storage/{record['name']}"
        # the scratch key must not reach the INSERT column list
        assert '_raw_img_url' not in record


def test_unverified_counts_rows_that_fell_back_to_the_rule_tier(fake_io, monkeypatch):
    """Every fixture row matches a committed override today, so `unverified` is
    0. Emptying the override file simulates upstream editing the text: a hash
    miss recomputes from the rule tier and is reported, never rejected."""
    monkeypatch.setattr(hours, 'OVERRIDES', {})

    main._execute_pipeline_run()

    assert pipeline_state.snapshot()['last_details']['unverified'] == 12


def test_unverified_lines_counts_rows_with_no_reviewed_break(fake_io, monkeypatch):
    """Counted separately from `unverified`: the two artifacts have independent
    keyspaces and regeneration commands, and a location can legitimately be
    verified for one and auto for the other. Emptying the override file leaves
    10 of the 12 fixture rows on the auto tier; 沼津グランドホテル and 安田屋旅館
    stay verified because all four of their fields are a single unbreakable
    token, which the fast path answers without an entry at all."""
    monkeypatch.setattr(display, 'OVERRIDES', {})

    main._execute_pipeline_run()

    details = pipeline_state.snapshot()['last_details']
    assert details['unverified'] == 0
    assert details['unverified_lines'] == 10


def test_run_against_an_existing_baseline(fake_io, baseline_kml):
    """The baseline is a KML in Storage, not a stored count - it gets written to
    a temp file and re-parsed on every run."""
    with open(baseline_kml, 'rb') as f:
        fake_io['baseline'] = f.read()

    main._execute_pipeline_run()

    assert pipeline_state.snapshot()['last_result'] == 'success'


# --- rollback --------------------------------------------------------------

def test_validation_failure_touches_neither_the_database_nor_the_baseline(fake_io, monkeypatch):
    """The whole point of the validation gate: a botched upstream export is
    discarded, and the previous baseline stays the accepted structure so the next
    run is still compared against known-good data."""
    def reject(placemarks, baseline_count, fields_by_row):
        raise PipelineValidationError('too many placemarks missing address: 90/136')

    monkeypatch.setattr(main, 'validate_structure', reject)

    main._execute_pipeline_run()

    snapshot = pipeline_state.snapshot()
    assert snapshot['running'] is False
    assert snapshot['last_result'] == 'error'
    assert snapshot['last_error'].startswith('KML structure validation failed')
    assert fake_io['upserted'] == []
    assert fake_io['uploaded'] == []


def test_a_shrunken_export_is_rejected_by_the_real_validator(
        fake_io, monkeypatch, sample_kml, baseline_kml):
    """End-to-end through the real validate_structure: a 12-placemark baseline
    against a 1-placemark download trips MIN_COUNT_RATIO. This is the botched
    upstream export the gate exists for."""
    with open(sample_kml, 'rb') as f:
        fake_io['baseline'] = f.read()
    with open(baseline_kml, 'rb') as f:
        shrunken = f.read()

    def fetch_shrunken(path, url=None):
        with open(path, 'wb') as target:
            target.write(shrunken)
        return path

    monkeypatch.setattr(main, 'fetch_kml', fetch_shrunken)

    main._execute_pipeline_run()

    assert 'count dropped too far' in pipeline_state.snapshot()['last_error']
    assert fake_io['upserted'] == []
    assert fake_io['uploaded'] == []


def test_an_upsert_failure_is_reported_and_leaves_the_baseline_alone(fake_io, monkeypatch):
    def explode(records):
        raise RuntimeError('connection pool exhausted')

    monkeypatch.setattr(main, 'upsert_locations', explode)

    main._execute_pipeline_run()

    snapshot = pipeline_state.snapshot()
    assert snapshot['last_result'] == 'error'
    assert 'pipeline processing error' in snapshot['last_error']
    assert 'connection pool exhausted' in snapshot['last_error']
    assert fake_io['uploaded'] == []


# --- the run slot is always released --------------------------------------

@pytest.mark.parametrize('seam', [
    'download_object',   # pre-flight: fetching the baseline from Storage
    'load_placemarks',   # pre-flight: parsing it
    'fetch_kml',         # the download itself
    'cache_images',      # photo caching
    'upsert_locations',  # the database write
    'upload_object',     # post-flight: promoting the new baseline
])
def test_every_failure_path_releases_the_run_slot(fake_io, monkeypatch, seam):
    """The invariant behind POST /pipeline/run: `running` must never be left set.

    pipeline_state is in-memory with no timeout, so an exception that escapes
    _execute_pipeline_run wedges the service - every later trigger answers
    'already_running', and the only cure is a restart. The pre-flight baseline
    download and the post-flight baseline upload used to sit outside the try
    block and did exactly that; the rest of the list is here so a future
    refactor cannot reintroduce the hole somewhere else.
    """
    def explode(*args, **kwargs):
        raise RuntimeError(f'{seam} is down')

    monkeypatch.setattr(main, seam, explode)
    pipeline_state.try_start()

    main._execute_pipeline_run()

    snapshot = pipeline_state.snapshot()
    assert snapshot['running'] is False, f'{seam} failure left the run slot claimed'
    assert snapshot['last_result'] == 'error'
    assert f'{seam} is down' in snapshot['last_error']


def test_the_slot_is_reusable_after_a_failure(fake_io, monkeypatch):
    """The practical consequence: a failed run must not block the next attempt."""
    def explode(key):
        raise RuntimeError('Storage unreachable')

    monkeypatch.setattr(main, 'download_object', explode)
    pipeline_state.try_start()
    main._execute_pipeline_run()

    assert pipeline_state.try_start() is True


def test_a_failed_baseline_fetch_does_not_reach_the_database(fake_io, monkeypatch):
    """Releasing the slot must not come at the cost of running on regardless -
    a baseline it cannot read means it cannot validate, so nothing is written."""
    def explode(key):
        raise RuntimeError('Storage unreachable')

    monkeypatch.setattr(main, 'download_object', explode)

    main._execute_pipeline_run()

    assert fake_io['upserted'] == []
    assert fake_io['uploaded'] == []
