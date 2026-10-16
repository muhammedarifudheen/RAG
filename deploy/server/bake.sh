#!/usr/bin/env bash
# Runs during the image build: adds the starter sources and saves them as a dump
# that ships inside the image (start.sh loads it into each new database). A free
# host keeps no data across restarts, and adding them at start-up takes minutes
# on its small CPU share; loading the dump takes seconds.
#
# A source that cannot be added now (a site down during the build) is left out,
# not fatal: start.sh adds whatever is not listed in /srv/seeded.txt.
set -euo pipefail
ATLAS_PGDATA=/tmp/bake-pgdata
source /srv/postgres.sh

start_postgres
: > /srv/seeded.txt
for url in ${SEED_SOURCES:-}; do
  echo "bake: adding $url"
  if python -m worker.ingest "$url" > /tmp/bake.log 2>&1; then
    echo "$url" >> /srv/seeded.txt
  else
    echo "bake: could not add $url; it will be added at start-up"
    tail -n 3 /tmp/bake.log
  fi
done
pg_dump -h 127.0.0.1 -U user --format=custom --no-owner atlas > "$SEED_DUMP"
stop_postgres
rm -rf "$PGDATA" /tmp/bake.log /tmp/postgres.log
echo "bake: $(wc -l < /srv/seeded.txt) source(s) built into the image ($(du -h "$SEED_DUMP" | cut -f1))"
