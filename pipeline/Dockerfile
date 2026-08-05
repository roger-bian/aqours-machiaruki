FROM python:3.10.20-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgdal-dev gdal-bin \
    && rm -rf /var/lib/apt/lists/*
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
# stdout is a block-buffered pipe under Docker - without this the pipeline's
# stage timings can sit in an 8KB buffer, or vanish entirely when the free-plan
# container spins down
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
# Debian bookworm's apt ships an older GDAL than the version pinned in
# requirements.txt for local dev (matched there against a dev machine's
# gdal-config). Re-pin to whatever's actually installed in this image
# instead of chasing a matching apt/PPA package version.
RUN GDAL_VERSION=$(gdal-config --version) && \
    sed -i "s/^GDAL==.*/GDAL==${GDAL_VERSION}/" requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
