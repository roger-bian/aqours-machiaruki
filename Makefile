# Local dev entry points. See CLAUDE.md / README.md for the credentials each
# side expects (pipeline/.env, web/.env.local - both gitignored).

.PHONY: help web pipeline test test-py test-web

help:
	@echo "make web       - Vite dev server for web/ (port 5173+)"
	@echo "make pipeline  - FastAPI pipeline service (port 8000)"
	@echo "make test      - both test suites (offline, ~2s)"
	@echo "make test-py   - pytest for pipeline/ only"
	@echo "make test-web  - vitest for web/ only"

# Static React + Vite + Leaflet frontend. Reads Supabase directly, so this is
# all that is needed to work on the map - no pipeline required.
web:
	cd web && npm run dev

# FastAPI service owning the KML -> Postgres pipeline. `uvicorn` resolves
# through pyenv's shims to the `aqours` virtualenv named in .python-version.
#
# WARNING: PIPELINE_DATABASE_URL in pipeline/.env points at the live Supabase,
# not a local Postgres - POST /pipeline/run from here writes to production.
pipeline:
	cd pipeline && uvicorn app.main:app --port 8000

# Both halves run fully offline - no network, no database. pytest needs
# `pip install -r pipeline/requirements-dev.txt` once; vitest comes from
# web/'s devDependencies.
test: test-py test-web

test-py:
	cd pipeline && python -m pytest

test-web:
	cd web && npm test
