#!/usr/bin/env bash
# Run the local SPEDIA app against the PostgreSQL URL configured in root .env.
set -euo pipefail
cd "$(dirname "$0")/.."

profile=".env.spedia.local"
env_file=".env"
[[ -f "$profile" ]] || { printf 'Missing %s\n' "$profile" >&2; exit 1; }
[[ -f "$env_file" ]] || { printf 'Missing %s\n' "$env_file" >&2; exit 1; }

set -a
source "$profile"
set +a

database_url="$(sed -n 's/^DATABASE_URL=//p' "$env_file" | head -n 1)"
if [[ ${database_url:0:1} == "'" && ${database_url: -1} == "'" ]] || [[ ${database_url:0:1} == '"' && ${database_url: -1} == '"' ]]; then
  database_url="${database_url:1:-1}"
fi
case "$database_url" in
  postgresql://*|postgresql+psycopg2://*) ;;
  *) printf 'Root .env must contain a PostgreSQL DATABASE_URL.\n' >&2; exit 1 ;;
esac
export DATABASE_URL="$database_url"
export ASSET_STORAGE=postgres
export ASSET_CACHE_ROOT="$PWD/data/runtime/neon-assets"
export FEATURE_PATH="$ASSET_CACHE_ROOT/data/spedia/features-temporal/features.parquet"
export ARTIFACT_ROOT="$ASSET_CACHE_ROOT/data/artifacts"
export REPLAY_DIRECTORY="$ASSET_CACHE_ROOT/data/spedia/review-v3"
export REALISTIC_REPLAY_DIRECTORY="$ASSET_CACHE_ROOT/data/spedia/replay-realistic-v1"
export INFERENCE_CONTEXT_DIRECTORY="$ASSET_CACHE_ROOT/data/inference/context-v1"

PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" -c 'import os, sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

url = os.environ["DATABASE_URL"]
parsed = make_url(url)
print("Neon PostgreSQL target: %s/%s" % (parsed.host or "local socket", parsed.database or "default"))
try:
    engine = create_engine(url, connect_args={"connect_timeout": 10})
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()
    engine.dispose()
except Exception as error:
    code = getattr(getattr(error, "orig", None), "pgcode", None)
    print("PostgreSQL connection failed: %s%s" % (type(error).__name__, " (SQLSTATE " + code + ")" if code else ""), file=sys.stderr)
    raise SystemExit(1)
print("PostgreSQL SELECT 1: %s" % result)
'

exec bash start.sh
