# Atlas's public server in one container: Postgres with pgvector, the API and the
# embedding model. The website itself is on GitHub Pages.
#
# Built from the repository root (render.yaml does this):
#   docker build -f deploy/server/Dockerfile .
# It is sized for a free host's 512 MB of memory; see the settings at the end.
FROM pgvector/pgvector:pg16

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/lib/postgresql/16/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/huggingface

RUN python3 -m venv /opt/venv && pip install --upgrade pip

COPY packages/shared /build/packages/shared
COPY apps/worker /build/apps/worker
COPY apps/api /build/apps/api
RUN pip install /build/packages/shared /build/apps/worker /build/apps/api

# Bake the embedding model in, so a restarted server does not download it.
RUN python -c "from worker.embed import load_model; load_model('sentence-transformers/all-MiniLM-L6-v2')"

# Postgres refuses to run as root, and hosts such as Hugging Face run as user 1000.
RUN useradd --create-home --uid 1000 user \
    && mkdir -p /srv/api \
    && cp /build/apps/api/alembic.ini /srv/api/ \
    && cp -r /build/apps/api/migrations /srv/api/ \
    && rm -rf /build \
    && chown -R user:user /srv /opt/huggingface
COPY --chown=user:user deploy/server/start.sh /srv/start.sh

USER user
WORKDIR /srv/api
# Memory: fewer malloc arenas keep the API small, and smaller embedding batches
# keep an ingest's peak down. PORT is replaced by the host's.
ENV HF_HUB_OFFLINE=1 \
    MALLOC_ARENA_MAX=2 \
    EMBEDDING_BATCH_SIZE=4 \
    PORT=7860 \
    DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/atlas
EXPOSE 7860
CMD ["bash", "/srv/start.sh"]
