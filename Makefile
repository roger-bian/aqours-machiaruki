# Local dev entry points. See CLAUDE.md / README.md for the credentials each
# side expects (pipeline/.env, web/.env.local - both gitignored).

.PHONY: help web pipeline

help:
	@echo "make web       - Vite dev server for web/ (port 5173+)"
	@echo "make pipeline  - FastAPI pipeline service (port 8000)"

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
