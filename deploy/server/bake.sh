#!/usr/bin/env bash
# Runs during the image build: adds the starter sources to a database that ships
# inside the image. A free host keeps no data across restarts, and adding them at
# start-up takes minutes on its small CPU share; baked in, they are there at once.
#
# A source that cannot be added now (a site down during the build) is left out,
# not fatal: start.sh adds whatever is not listed in /srv/seeded.txt.
set -euo pipefail
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
stop_postgres
rm -f /tmp/bake.log /tmp/postgres.log
echo "bake: $(wc -l < /srv/seeded.txt) source(s) built into the image"
