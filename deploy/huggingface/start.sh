#!/usr/bin/env bash
# Starts Postgres, migrates, re-adds the starter sources in the background, and
# runs the API. A free Space keeps no data across restarts, so every start is a
# fresh database: SEED_SOURCES is how the public site gets its content back.
set -euo pipefail

PGDATA=/tmp/pgdata
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  initdb -D "$PGDATA" -U user --auth=trust --encoding=UTF8 > /dev/null
fi
pg_ctl -D "$PGDATA" -l /tmp/postgres.log -w start \
  -o "-c listen_addresses=127.0.0.1 -p 5432 -c unix_socket_directories=/tmp"
createdb -h 127.0.0.1 -U user atlas 2> /dev/null || true

alembic upgrade head

if [ -n "${SEED_SOURCES:-}" ]; then
  (
    # One link per line (or separated by spaces). Added one at a time, after the
    # API is up, so the site answers while the knowledge base fills.
    sleep 20
    for url in $SEED_SOURCES; do
      echo "seeding: $url"
      python -m worker.ingest "$url" > /tmp/seed.log 2>&1 \
        && echo "seeded: $url" || { echo "seed failed: $url"; tail -n 3 /tmp/seed.log; }
    done
  ) &
fi

# Hugging Face's proxy is the only way in, so its forwarded client address is
# trusted; the rate limiter depends on it.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" \
  --proxy-headers --forwarded-allow-ips='*'
