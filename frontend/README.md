# Tracely AI SPEDIA frontend

React/Vite analyst dashboard for the authenticated FastAPI SPEDIA API. SessionGate manages login; apiFetch sends credentialed requests and CSRF headers; pages consume persisted source-backed results.

```bash
npm ci
npm run dev
npm run lint
npm run build
```

Vite serves 127.0.0.1:8000 and proxies /api and /health to 127.0.0.1:5000. Set API_PROXY_TARGET for a different development backend. VITE_API_URL defaults to same-origin requests. Private frontend .env files and build outputs are excluded.

Replay is historical playback. New Data Inference accepts only the supported native SPEDIA stream contract with verified prior context. Department metadata is unavailable. Existing graph geometry is display layout over observed user-host associations.

Use the repository README for backend/database/asset prerequisites. Production container builds serve dist through unprivileged Nginx. This source snapshot excludes obsolete Flask-based browser harnesses.
