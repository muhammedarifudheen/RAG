#!/usr/bin/env bash
# Starts Postgres, migrates, re-adds the starter sources in the background, and
# runs the API. A free host keeps no data across restarts, so every start is a
# fresh database: SEED_SOURCES is how the public site gets its content back.
set -euo pipefail

PGDATA=/tmp/pgdata
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  initdb -D "$PGDATA" -U user --auth=trust --encoding=UTF8 > /dev/null
fi
# A small Postgres: the knowledge base is small, and the host has 512 MB in all.
pg_ctl -D "$PGDATA" -l /tmp/postgres.log -w start \
  -o "-c listen_addresses=127.0.0.1 -p 5432 -c unix_socket_directories=/tmp \
      -c shared_buffers=16MB -c max_connections=20 -c work_mem=4MB \
      -c maintenance_work_mem=32MB -c max_worker_processes=2 \
      -c max_parallel_workers=0 -c max_parallel_workers_per_gather=0"
createdb -h 127.0.0.1 -U user atlas 2> /dev/null || true

alembic upgrade head

if [ -n "${SEED_SOURCES:-}" ]; then
  # Added through the running API rather than a separate process, so the embedding
  # model is loaded once. One at a time, once the API is up, so the site answers
  # while the knowledge base fills.
  python - <<'PY' &
import json, os, time, urllib.request

api = f"http://127.0.0.1:{os.environ.get('PORT', '7860')}"
headers = {"Content-Type": "application/json"}
if os.environ.get("ADMIN_TOKEN"):
    headers["Authorization"] = f"Bearer {os.environ['ADMIN_TOKEN']}"

for _ in range(300):
    try:
        urllib.request.urlopen(f"{api}/healthz", timeout=3)
        break
    except OSError:
        time.sleep(2)

for url in os.environ["SEED_SOURCES"].split():
    print(f"seeding: {url}", flush=True)
    request = urllib.request.Request(
        f"{api}/ingest", data=json.dumps({"url": url}).encode(), headers=headers
    )
    outcome = "no result"
    try:
        with urllib.request.urlopen(request, timeout=1800) as stream:
            event = None
            for raw in stream:
                line = raw.decode().strip()
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event in ("done", "error"):
                    outcome = f"{event} {line[5:].strip()}"
    except OSError as error:
        outcome = f"error {error}"
    status = "seeded" if outcome.startswith("done") else "seed failed"
    print(f"{status}: {url} ({outcome})", flush=True)
PY
fi

# The host's proxy is the only way in, so its forwarded client address is
# trusted; the rate limiter depends on it.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" \
  --proxy-headers --forwarded-allow-ips='*'
