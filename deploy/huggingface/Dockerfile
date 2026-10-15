# Atlas's server for a Hugging Face Space: Postgres with pgvector, the API and the
# embedding model in one container. The website itself is on GitHub Pages.
#
# The Space's files are assembled by scripts/deploy-huggingface.ps1: this file
# becomes the Space's Dockerfile, next to packages/, apps/api and apps/worker.
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

# CPU-only PyTorch: the default wheel bundles CUDA libraries a CPU Space cannot use.
# Only torch itself comes from the CPU index (which lacks some of its build-time
# helpers); its ordinary dependencies are installed from PyPI with the rest below.
RUN python3 -m venv /opt/venv \
    && pip install --upgrade pip \
    && pip install --no-deps --index-url https://download.pytorch.org/whl/cpu torch

COPY packages/shared /build/packages/shared
COPY apps/worker /build/apps/worker
COPY apps/api /build/apps/api
RUN pip install /build/packages/shared /build/apps/worker /build/apps/api

# Bake the embedding model in, so a restarted Space does not download it.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Spaces run the container as user 1000; Postgres refuses to run as root anyway.
RUN useradd --create-home --uid 1000 user \
    && mkdir -p /srv/api \
    && cp /build/apps/api/alembic.ini /srv/api/ \
    && cp -r /build/apps/api/migrations /srv/api/ \
    && rm -rf /build \
    && chown -R user:user /srv /opt/huggingface
COPY --chown=user:user start.sh /srv/start.sh

USER user
WORKDIR /srv/api
ENV HF_HUB_OFFLINE=1 \
    PORT=7860 \
    DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/atlas
EXPOSE 7860
CMD ["bash", "/srv/start.sh"]
