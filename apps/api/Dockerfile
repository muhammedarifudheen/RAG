# The Atlas backend image: the API service, and the migrate and ingest jobs.
# apps/api and apps/worker import each other, so they ship as one image and the
# jobs override the command.
#
# Build from the repo root:
#   docker build -f apps/api/Dockerfile -t atlas-backend .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/huggingface

WORKDIR /build
COPY packages/shared packages/shared
COPY apps/worker apps/worker
COPY apps/api apps/api
RUN pip install ./packages/shared ./apps/worker ./apps/api

# Bake the embedding model in, so no instance downloads it at startup.
RUN python -c "from worker.embed import load_model; load_model('sentence-transformers/all-MiniLM-L6-v2')"

# Alembic needs its config and migration scripts next to the working directory.
WORKDIR /srv/api
RUN cp /build/apps/api/alembic.ini . \
    && cp -r /build/apps/api/migrations . \
    && rm -rf /build \
    && useradd --create-home atlas \
    && chown -R atlas:atlas /opt/huggingface

USER atlas
ENV HF_HUB_OFFLINE=1 \
    PORT=8080
EXPOSE 8080

# --proxy-headers: Cloud Run's front end is the only way in, and the rate limiter
# needs the caller's address rather than the proxy's.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
