# Build from the repo root, because the backend also needs schemes/:
#   docker build -f backend/Dockerfile -t entitled-backend .
FROM python:3.10-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    ENTITLED_DATA_DIR=/data

WORKDIR /srv/backend

# libgl1 and libglib2.0-0 are what RapidOCR's OpenCV needs. Playwright brings Chromium's own libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium

COPY backend/app ./app
COPY schemes /srv/schemes

RUN useradd --create-home --uid 10001 entitled \
    && mkdir /data \
    && chown entitled /data
USER entitled
VOLUME /data

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:' + os.environ.get('PORT', os.environ['BACKEND_PORT']) + '/api/health', timeout=4)" || exit 1

# Hosts usually assign PORT. The form agent reaches the portal through BACKEND_PORT, so the two must agree.
# One worker only: each worker would run its own status poller.
ENV BACKEND_PORT=8000
CMD ["sh", "-c", "export BACKEND_PORT=${PORT:-$BACKEND_PORT}; exec python -m uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT --workers 1"]
