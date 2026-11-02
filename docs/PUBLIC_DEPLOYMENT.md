# Deploy the public SPEDIA dashboard

The current frontend and FastAPI backend do not require login. All enabled API
actions, including exports, imports, alert updates and model activation, are
accessible to anyone who can reach the service. Actions are recorded with actor
`public`; this is not a verified user identity. Runtime retraining remains disabled.

## Render backend

Deploy the commit containing this access change. Required configuration still
includes `DATABASE_URL`, valid published SPEDIA records and the existing artifact
and feature storage configuration. Removing login does not create database tables
or provision model files.

Set `PYTHON_VERSION=3.11.11`, `APP_ENV=production`, and
`FRONTEND_URL=https://tracely-ai.vercel.app` (or your frontend's actual origin).
`SESSION_SECRET`, `DEV_AUTH_USERS`, and `OIDC_*` are no longer read by the active
application and may be removed from the service environment.

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
gunicorn src.api.app:app --worker-class uvicorn.workers.UvicornWorker --workers 1 --bind 0.0.0.0:$PORT --timeout 120
```

Use `/health/live` for the liveness check. `/health/ready` also checks database and
active-model readiness. Apply reviewed migrations and provision durable assets
through the existing deployment process.

## Frontend

Deploy the frontend from the same version. Configure `VITE_API_URL` to the backend
origin, without `/api`, then rebuild. A same-origin reverse proxy can instead use
an empty value. The browser no longer sends authentication cookies or CSRF tokens,
and the dashboard no longer calls `/api/auth/*`.

An old cached frontend still displaying a login screen needs a frontend redeploy
and reload. The removed authentication endpoints return 404 by design.

## Checks

```bash
.venv/bin/python -m pytest tests/test_public_api.py tests/test_startup.py -q
cd frontend
npm run lint
npm run build
```

After deployment, `/health/live` should return 200. Public dashboard requests
should return their data or a specific data/storage validation error, without
requiring a login. This code change does not push or deploy itself.

Security audit results and remaining public-access risks: [security review](SECURITY_REVIEW.md).

The owner-selected main output is [SPEDIA V6 Maximum](V6_MAIN_MODEL.md). Versioned assets must be materialized before activating a newly staged version. Its main metrics are reused validation, not an independent test.
