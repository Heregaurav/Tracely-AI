#!/usr/bin/env bash
# Apply migrations and serve approved frozen inference; never generate or train.
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-.venv/bin/python}"
: "${DATABASE_URL:?Set DATABASE_URL; see docs/DEPLOYMENT.md}"
pids=()
cleanup() {
  if ((${#pids[@]})); then kill "${pids[@]}" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
"$PYTHON" -m alembic upgrade head
if [[ "${ASSET_STORAGE:-}" == "postgres" ]]; then
  "$PYTHON" -m scripts.sync_neon_assets materialize --root "$PWD" --cache "${ASSET_CACHE_ROOT:-data/runtime/neon-assets}"
fi
"$PYTHON" -m gunicorn -c gunicorn.conf.py src.api.app:app &
pids+=("$!")
(cd frontend && npm run dev) &
pids+=("$!")
wait -n "${pids[@]}"
