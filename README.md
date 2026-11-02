# Tracely AI — SPEDIA

SPEDIA v2 behavioral anomaly review with a React/Vite dashboard, FastAPI backend, PostgreSQL, and frozen scikit-learn inference. This branch contains the SPEDIA implementation only. CERT/LANL pipelines, historical synthetic-demo code, raw datasets, model binaries, local credentials, runtime state and unrelated experiment reports are excluded.

The approved model remains `spedia-dcd995bcea1644cabd261b4bcc4dd223`. Its historical result is 86% precision and 46.49% recall on 421 retained test user-hours. Those controlled mixed-origin results do not establish enterprise detection accuracy; source-generation markers correlate perfectly with native event labels. Separate SPEDIA development experiments are not activated automatically.

## Existing configured installation

```bash
bash scripts/run_local_neon.sh
```

Open http://127.0.0.1:8000. This launcher requires private `.env` and `.env.spedia.local` files, a configured PostgreSQL database and previously provisioned serving assets. It applies pending migrations, verifies/materializes stored assets and starts the backend/frontend. It never retrains on startup. Credentials are not distributed with the repository.

## Backend and frontend separately

Install Python dependencies into a virtual environment and install frontend dependencies with `npm --prefix frontend ci`. Configure environment variables using `.env.example`; do not commit actual credentials. Database schema and frozen assets must be provisioned before serving results.

```bash
# In a configured development shell:
.venv/bin/python -m uvicorn src.api.app:app --host 127.0.0.1 --port 5000
# In another terminal:
npm --prefix frontend run dev
```

The backend reads environment variables, not a config.yaml file. `/health/live` checks the process and `/health/ready` checks serving prerequisites. `/docs` is available in development. Production requires durable trusted artifacts. Authentication has been removed; the dashboard opens directly and enabled API actions are public. See [deployment instructions](docs/PUBLIC_DEPLOYMENT.md).

## Implemented workflows

- Thirty causal observed-user-hour features from native SPEDIA activity.
- Frozen IF/neural/host-novelty scoring, versioned PostgreSQL scores, and persistent analyst investigations.
- Historical replay: batch scoring with separate annotations, not a live telemetry collector.
- Constrained native CSV imports with verified prior context and separate persisted predictions.
- Public API access, audit entries attributed to `public`, and digest-verified trusted model loading.
- Explicit offline SPEDIA feature/training/review scripts. No runtime retraining or automated model replacement.

`src/data/spedia.py` owns the data contract; `src/models/behavioral.py` owns model scoring; `src/inference/` handles new imports; `src/db/` owns publication, replay and persistence; `src/api/` serves FastAPI; `frontend/src/` provides the analyst UI. `migrations/` holds Alembic revisions. Docker/Compose and an API-only Render reference configuration are included; this source push does not deploy them.

## Verification

```bash
.venv/bin/python -m pytest -q tests
npm --prefix frontend run lint
npm --prefix frontend run build
```

Real-artifact tests skip when private datasets/checkpoints are unavailable. PostgreSQL integration requires a fresh dedicated `tracely_test*` database through TEST_DATABASE_URL; never point integration tests at a deployed database. Historical browser harnesses that import the retired Flask service are excluded from this snapshot.

## Data and artifact provisioning

Raw CSVs, features, model weights, replay/context files and stored database assets are private/external prerequisites, not Git contents. Restore reviewed assets through your established PostgreSQL asset store or trusted filesystem provisioning process. `scripts/sync_neon_assets.py` performs explicit uploads or local materialization; uploads modify database state and are never run automatically by a Git push.

No password, private endpoint, session secret or model weight is included in this branch. The local working checkout may contain other experiments; they are not part of this published source tree.
