# Postgres for the one-container server; sourced by bake.sh (image build) and
# start.sh (each start), so both run the database the same way.
PGDATA=/srv/pgdata

start_postgres() {
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
  (cd /srv/api && alembic upgrade head)
}

stop_postgres() {
  pg_ctl -D "$PGDATA" -w -m fast stop > /dev/null
}
