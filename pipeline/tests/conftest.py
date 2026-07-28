"""Shared test setup. Three things here are load-bearing and order-sensitive.

1. The environment is set *before* any `app.*` import. `app/auth.py` reads
   AUTH0_DOMAIN / AUTH0_CLIENT_ID / ALLOWED_EMAILS with bare `os.environ[...]`
   at module level, so importing `app.main` raises KeyError otherwise. Setting
   them here also wins over the real `pipeline/.env`: `load_dotenv()` in
   `app/main.py` does not override variables that are already set - which
   matters because that file's PIPELINE_DATABASE_URL points at production.

2. `app.kml` is imported before anything else can pull in geotable/osgeo. It
   sets `OGR_SKIP=LIBKML`, and GDAL's driver choice locks on first import; get
   the order wrong and the KML's description field arrives lowercase, which
   geotable deletes outright.

3. `psycopg2.connect` is stubbed to raise for every test. `PIPELINE_DATABASE_URL`
   normally points at the live Supabase and there is no staging DB, so "a test
   cannot reach the database" is enforced rather than assumed.
"""
import os

os.environ['AUTH0_DOMAIN'] = 'test-tenant.example.auth0.com'
os.environ['AUTH0_CLIENT_ID'] = 'test-client-id'
os.environ['ALLOWED_EMAILS'] = 'allowed@example.com,other@example.com'
os.environ['PIPELINE_DATABASE_URL'] = 'postgresql://tests-must-not-connect'
os.environ['SUPABASE_URL'] = 'https://test-project.supabase.co'
os.environ['SUPABASE_SECRET_KEY'] = 'test-secret-key'
os.environ['SUPABASE_BUCKET'] = 'test-bucket'

import app.kml  # noqa: E402  - must precede any other geotable/osgeo import

import psycopg2  # noqa: E402
import pytest  # noqa: E402

from app import pipeline_state  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Hard stop on any un-faked DB access. Tests that exercise
    `upsert_locations` re-patch `psycopg2.connect` themselves."""
    def refuse(*args, **kwargs):
        raise AssertionError(
            'a test tried to open a real database connection - patch '
            'app.db.upsert_locations or psycopg2.connect in the test'
        )

    monkeypatch.setattr(psycopg2, 'connect', refuse)


@pytest.fixture(autouse=True)
def clean_pipeline_state():
    """`app.pipeline_state` keeps its run flag in module globals, so state
    leaks between tests unless it is reset."""
    pipeline_state.finish(None)
    yield
    pipeline_state.finish(None)


@pytest.fixture
def sample_kml():
    """Six real placemarks trimmed from a live export; see the comment at the
    top of the file for what each one covers."""
    return os.path.join(FIXTURES, 'sample.kml')


@pytest.fixture
def baseline_kml():
    """A one-placemark KML, for validation's count-drop check."""
    return os.path.join(FIXTURES, 'baseline_small.kml')


@pytest.fixture
def placemarks(sample_kml):
    return app.kml.load_placemarks(sample_kml)
