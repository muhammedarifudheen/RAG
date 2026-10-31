#!/usr/bin/env bash
# Starts Postgres and the API, and adds any starter sources the image does not
# already hold. A free host keeps no data across restarts, so every start begins
# from the database built into the image (see bake.sh).
set -euo pipefail
source /srv/postgres.sh
# The host's logs show only this script's output, so a failed start shows the
# database's own log too.
trap 'echo "start: failed; the database log follows"; tail -n 30 /tmp/postgres.log' ERR

start_postgres
echo "start: database ready; starting the API"

# In the background, once the API is up: load the embedding model with one search,
# so the first visitor does not wait for it, then add any starter sources missing
# from the image. They go through the running API rather than a separate process,
# so the model is in memory once, and one at a time, so the site answers meanwhile.
python - <<'PY' &
import json, os, time, urllib.request

api = f"http://127.0.0.1:{os.environ.get('PORT', '7860')}"
headers = {"Content-Type": "application/json"}
if os.environ.get("ADMIN_TOKEN"):
    headers["Authorization"] = f"Bearer {os.environ['ADMIN_TOKEN']}"
try:
    with open("/srv/seeded.txt", encoding="utf-8") as baked:
        in_image = set(baked.read().split())
except OSError:
    in_image = set()
missing = [url for url in os.environ.get("SEED_SOURCES", "").split() if url not in in_image]

for _ in range(300):
    try:
        urllib.request.urlopen(f"{api}/healthz", timeout=3)
        break
    except OSError:
        time.sleep(2)
try:
    urllib.request.urlopen(f"{api}/search?q=warm+up&limit=1", timeout=600)
    print("embedding model loaded", flush=True)
except OSError:
    pass  # an empty knowledge base: the first ingest loads the model instead

# The answer log, kept on the repository's knowledge-log branch by the knowledge-log
# workflow: restored into this fresh database, so the knowledge health carries on.
log_url = os.environ.get("KNOWLEDGE_LOG_URL")
if log_url and "Authorization" in headers:
    try:
        with urllib.request.urlopen(log_url, timeout=60) as kept:
            log = json.load(kept)
        request = urllib.request.Request(
            f"{api}/health",
            data=json.dumps({"action": "import", "data": log}).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=600) as restored:
            print(f"knowledge log: {restored.read().decode()}", flush=True)
    except (OSError, ValueError) as error:
        print(f"knowledge log not restored ({error})", flush=True)

for url in missing:
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

# The host's proxy is the only way in, so its forwarded client address is
# trusted; the rate limiter depends on it.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" \
  --proxy-headers --forwarded-allow-ips='*'
