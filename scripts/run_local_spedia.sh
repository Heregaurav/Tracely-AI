#!/usr/bin/env bash
# Use the existing private SPEDIA profile without modifying other local settings.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
source .env.spedia.local
set +a
pg_bin="${PG_BIN:-/usr/lib/postgresql/16/bin}"
if ! "$pg_bin/pg_ctl" -D data/runtime/postgres status >/dev/null 2>&1; then
  mkdir -p /tmp/tracely-live-socket
  chmod 700 /tmp/tracely-live-socket
  "$pg_bin/pg_ctl" -D data/runtime/postgres -l data/runtime/postgres/server.log -o "-k /tmp/tracely-live-socket -p 55440 -c listen_addresses=''" start
fi
exec bash start.sh
