# Postgres for the one-container server; sourced by bake.sh (image build) and
# start.sh (each start), so both run the database the same way.
#
# The database is always created where it runs, never shipped as a data
# directory inside the image: Render could not start Postgres on a directory
# that came from the image. The starter sources travel as a dump instead.
# Its own name: the base image already sets PGDATA, to a directory this user cannot use.
PGDATA=${ATLAS_PGDATA:-/tmp/pgdata}
SEED_DUMP=/srv/seed.dump

start_postgres() {
  local fresh=no
  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    initdb -D "$PGDATA" -U user --auth=trust --encoding=UTF8 > /dev/null
    fresh=yes
  fi
  # A small Postgres: the knowledge base is small, and the host has 512 MB in all.
  pg_ctl -D "$PGDATA" -l /tmp/postgres.log -w start \
    -o "-c listen_addresses=127.0.0.1 -p 5432 -c unix_socket_directories=/tmp \
        -c shared_buffers=16MB -c max_connections=20 -c work_mem=4MB \
        -c maintenance_work_mem=32MB -c max_worker_processes=2 \
        -c max_parallel_workers=0 -c max_parallel_workers_per_gather=0"
  createdb -h 127.0.0.1 -U user atlas 2> /dev/null || true
  if [ "$fresh" = yes ] && [ -s "$SEED_DUMP" ]; then
    echo "postgres: loading the starter sources built into the image"
    pg_restore -h 127.0.0.1 -U user -d atlas --no-owner --exit-on-error "$SEED_DUMP"
  fi
  (cd /srv/api && alembic upgrade head)
}

stop_postgres() {
  pg_ctl -D "$PGDATA" -w -m fast stop > /dev/null
}
