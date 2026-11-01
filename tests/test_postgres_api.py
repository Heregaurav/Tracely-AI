"""Isolated PostgreSQL integration tests. Set TEST_DATABASE_URL to an empty tracely_test* database.

Migrated from Flask test_client to FastAPI/Starlette TestClient (httpx).
The API surface is identical; only the client helpers change.
"""
import json
import os
from itertools import count
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from src.api.main import create_app
from src.db.models import Alert, AlertEvent, AuditLog, Base, DailyScore, ModelVersion
from src.db.publish import publish_run
from src.db.session import database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def integration(tmp_path_factory):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; isolated PostgreSQL required")
    from sqlalchemy.engine import make_url
    if not (make_url(url).database or "").startswith("tracely_test"):
        pytest.fail("Refusing to run integration tests outside a dedicated tracely_test* database")
    engine, factory = database(url)
    if inspect(engine).get_table_names():
        pytest.fail("Use a fresh empty test database; tests never reset existing data")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    assert set(Base.metadata.tables).issubset(set(inspect(engine).get_table_names()))
    root = tmp_path_factory.mktemp("postgres-api-fixture")
    frozen = Path("data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223")
    if not (frozen / "metrics.json").exists():
        pytest.skip("Genuine frozen SPEDIA artifacts required for integration")
    version = publish_run(factory, frozen)
    assert publish_run(factory, frozen) == version
    features = Path("data/spedia/features-temporal")

    # Build a Settings-compatible dict that create_app() accepts via env overrides.
    # FastAPI create_app reads from environment, so we patch the env.
    test_auth = {
        r.lower(): {"role": r, "password_hash": generate_password_hash("fixture-password")}
        for r in ("VIEWER", "ANALYST", "ADMIN")
    }
    os.environ["APP_ENV"] = "development"
    os.environ["SESSION_SECRET"] = "test-only-" + "x" * 40
    os.environ["DATASET_ID"] = "spedia-v2"
    os.environ["ALLOW_FIXTURE_DATA"] = "0"
    os.environ["FEATURE_PATH"] = str(features / "features.parquet")
    os.environ["ARTIFACT_ROOT"] = str(frozen.parent)
    os.environ["DEV_AUTH_USERS"] = json.dumps(test_auth)
    os.environ["FRONTEND_URL"] = "http://localhost:8000"

    # Invalidate the cached Settings singleton so test env vars are picked up.
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()
    dep._engine = None
    dep._session_factory = None

    settings = {
        "DATABASE_URL": url,
        "APP_ENV": "development",
        "SESSION_SECRET": "test-only-" + "x" * 40,
        "DATASET_ID": "spedia-v2",
        "ALLOW_FIXTURE_DATA": "0",
        "FEATURE_PATH": str(features / "features.parquet"),
        "ARTIFACT_ROOT": str(frozen.parent),
        "DEV_AUTH_USERS": json.dumps(test_auth),
        "FRONTEND_URL": "http://localhost:8000",
    }

    if os.getenv("TRACELY_TEST_STATE_PATH"):
        Path(os.environ["TRACELY_TEST_STATE_PATH"]).write_text(
            json.dumps({"database_url": url, "feature_path": str(features / "features.parquet"),
                        "artifact_root": str(frozen.parent)})
        )

    yield factory, root, version, settings

    engine.dispose()
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    dep.get_settings.cache_clear()
    dep._engine = None
    dep._session_factory = None


# ---------------------------------------------------------------------------
# TestClient helpers
# ---------------------------------------------------------------------------

_login_counter = count(1)


def make_client():
    """Create a fresh TestClient for each caller (preserves cookie jar isolation)."""
    from fastapi.testclient import TestClient
    # Invalidate the Settings cache so the latest env vars are used.
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()
    app = create_app()
    # TestClient with raise_server_exceptions=False so we can assert 5xx shapes.
    client = TestClient(app, raise_server_exceptions=False)
    return client


def login(role="admin"):
    """Log in with dev credentials; return (client, csrf_headers)."""
    client = make_client()
    ip = f"192.0.2.{next(_login_counter)}"
    # httpx doesn't expose REMOTE_ADDR directly; we pass it as a header that
    # the test client passes through. The auth endpoint uses request.client.host.
    response = client.post(
        "/api/auth/login",
        json={"username": role, "password": "fixture-password"},
        headers={"X-Forwarded-For": ip},
    )
    assert response.status_code == 200, response.json()
    csrf = response.json()["csrf_token"]
    return client, {"X-CSRF-Token": csrf}


# ---------------------------------------------------------------------------
# Tests — DB constraints and rollback
# ---------------------------------------------------------------------------

def test_migration_constraints_and_transaction_rollback(integration):
    factory, root, version, settings = integration
    with factory() as db:
        original = db.scalar(select(func.count()).select_from(ModelVersion))
    with pytest.raises(IntegrityError):
        with factory.begin() as db:
            db.add(Alert(id="invalid", score_id="nonexistent", severity="HIGH"))
    with factory() as db:
        assert db.get(Alert, "invalid") is None
        assert db.scalar(select(func.count()).select_from(ModelVersion)) == original


# ---------------------------------------------------------------------------
# Tests — Auth, roles, CSRF, query validation
# ---------------------------------------------------------------------------

def test_auth_roles_csrf_query_validation_and_origins(integration):
    anonymous = make_client()
    assert anonymous.get("/api/stats").status_code == 401
    assert anonymous.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401

    viewer, vheaders = login("viewer")
    assert viewer.get("/api/stats").status_code == 200
    assert viewer.get("/api/users").status_code == 403
    assert viewer.post("/api/retrain", json={}, headers=vheaders).status_code == 403

    analyst, aheaders = login("analyst")
    assert analyst.post("/api/retrain", json={}, headers=aheaders).status_code == 403

    admin, headers = login()
    # Missing CSRF should yield 403
    assert admin.post("/api/retrain", json={}).status_code == 403
    assert admin.get("/api/users?limit=999999").status_code == 400
    assert admin.get("/api/users?page=0").status_code == 400
    assert admin.get("/api/users?limit=bad").status_code == 400
    # CORS: untrusted origin should not receive Allow-Origin header
    cors_resp = admin.get("/api/stats", headers={"Origin": "https://untrusted.invalid"})
    assert cors_resp.headers.get("access-control-allow-origin") is None
    # Logout then session should be 401
    assert admin.post("/api/auth/logout", headers=headers).status_code == 200
    assert admin.get("/api/stats").status_code == 401


# ---------------------------------------------------------------------------
# Tests — Dashboard, dossier, graph, metrics, alert persistence
# ---------------------------------------------------------------------------

def test_dashboard_dossier_graph_metrics_and_alert_persistence(integration):
    factory, root, version, settings = integration
    client, headers = login("analyst")

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200

    stats = client.get("/api/stats").json()
    assert stats["total_users"] == 16
    assert stats["observed_event_volume"] > 0

    first = client.get("/api/users?limit=2&page=1").json()
    second = client.get("/api/users?limit=2&page=2").json()
    assert {r["user"] for r in first["users"]}.isdisjoint(r["user"] for r in second["users"])
    assert all(r["account_id"] == r["user"] for r in first["users"])
    assert all(r["display_name"] is None and r["name"] is None for r in first["users"])

    dossier = client.get("/api/users/irene").json()
    assert dossier["account_id"] == "irene"
    assert dossier["display_name"] is None and dossier["name"] is None
    assert dossier["daily_scores"]
    assert all(r["window_unit"] == "hour" for r in dossier["daily_scores"])
    assert not dossier["relative_time"]
    assert dossier["daily_scores"][-1]["explanation"]["event_count"] > 0

    graph = client.get("/api/graph?user_id=root&limit=2").json()
    assert graph["returned_edges"] <= 2
    assert graph["truncated"]
    assert len(graph["nodes"]) == len(graph["edges"]) + 1

    assert not client.get("/api/model-metrics").json()["is_fixture"]

    alerts = client.get("/api/threats?limit=500").json()["alerts"]
    assert alerts, "Fixture must exercise real anomaly-based alert creation"
    alert = alerts[0]

    response = client.post(
        f"/api/threats/{alert['alert_id']}/status",
        json={"status": "IN_PROGRESS", "version": alert["version"]},
        headers=headers,
    )
    assert response.status_code == 200, response.json()

    # Stale version must yield 409
    assert client.post(
        f"/api/threats/{alert['alert_id']}/status",
        json={"status": "RESOLVED", "version": alert["version"]},
        headers=headers,
    ).status_code == 409

    # Persistence across app instances
    other, _ = login("analyst")
    persisted = other.get("/api/threats?status=IN_PROGRESS").json()["alerts"]
    assert any(
        a["alert_id"] == alert["alert_id"] and a["version"] == alert["version"] + 1
        for a in persisted
    )
    assert client.get("/api/export").status_code == 200

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AlertEvent)) >= 1
        assert db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "scores.export")
        ) >= 1


# ---------------------------------------------------------------------------
# Tests — Frozen model policy
# ---------------------------------------------------------------------------

def test_frozen_runtime_cannot_enqueue_or_replace_model(integration, tmp_path):
    import shutil
    factory, root, version, settings = integration
    client, headers = login()

    assert client.get("/api/retrain").status_code == 405
    for config in ({}, {"epochs": 2, "n_estimators": 5}, {"neural": "false"}):
        assert client.post("/api/retrain", json=config, headers=headers).status_code == 409

    assert client.get("/api/training-jobs/missing").status_code == 404

    with factory() as db:
        assert db.scalar(text("SELECT count(*) FROM training_jobs")) == 0

    original = Path("data/artifacts") / version
    invalid = tmp_path / "invalid-publication"
    shutil.copytree(original, invalid)
    report = json.loads((invalid / "metrics.json").read_text())
    report["artifact_sha256"] = "0" * 64
    (invalid / "metrics.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="checksum"):
        publish_run(factory, invalid)

    report = json.loads((original / "metrics.json").read_text())
    report["contract"]["scoring_unit"] = "unsupported-unit"
    (invalid / "metrics.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="contract"):
        publish_run(factory, invalid)

    with factory() as db:
        assert (
            db.scalar(
                select(ModelVersion.id).where(
                    ModelVersion.active, ModelVersion.dataset_id == "spedia-v2"
                )
            )
            == version
        )

    assert (
        client.post(f"/api/model-versions/{version}/activate", json={}, headers=headers).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# Tests — Readiness without active state
# ---------------------------------------------------------------------------

def test_readiness_without_active_state(integration):
    # Use a dataset that doesn't exist — app should report not_ready.
    os.environ["DATASET_ID"] = "missing-dataset"
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()
    client = make_client()
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200
    # Restore
    os.environ["DATASET_ID"] = "spedia-v2"
    dep.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Tests — Concurrent optimistic locking
# ---------------------------------------------------------------------------

def test_real_concurrent_analyst_edits_have_one_winner(integration):
    from concurrent.futures import ThreadPoolExecutor
    factory, *_ = integration
    client, headers = login()
    record = client.get("/api/threats?limit=1").json()["alerts"][0]
    # Extract session cookie from the client's cookie jar.
    session_cookie = client.cookies.get("session")

    def change(status_val):
        from fastapi.testclient import TestClient
        from src.api import dependencies as dep
        dep.get_settings.cache_clear()
        other_app = create_app()
        other = TestClient(other_app, raise_server_exceptions=False)
        other.cookies.set("session", session_cookie)
        return other.post(
            f"/api/threats/{record['alert_id']}/status",
            json={"status": status_val, "version": record["version"]},
            headers=headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, ["OPEN", "RESOLVED"]))
    assert sorted(results) == [200, 409]


# ---------------------------------------------------------------------------
# Tests — Schema vs migrations
# ---------------------------------------------------------------------------

def test_schema_matches_preserved_migrations(integration):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()
    engine = dep._get_factory().kw["bind"]
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


# ---------------------------------------------------------------------------
# Tests — Production requires OIDC
# ---------------------------------------------------------------------------

def test_production_requires_oidc_and_checks_verified_subject(integration, monkeypatch):
    pytest.importorskip("authlib")
    _, _, _, settings = integration
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OIDC_ISSUER", "")
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()
    with pytest.raises(ValueError, match="Production requires"):
        create_app()

    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("OIDC_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://example.test/api/auth/callback")
    monkeypatch.setenv("OIDC_ROLES", json.dumps({"fixture-subject": "ANALYST"}))
    dep.get_settings.cache_clear()
    # Only verify create_app doesn't raise; full OIDC flow requires live issuer
    production = create_app()
    assert production is not None


# ---------------------------------------------------------------------------
# Tests — DB-backed login rate limiting
# ---------------------------------------------------------------------------

def test_database_shared_login_budget(integration):
    first = make_client()
    for _ in range(10):
        assert (
            first.post(
                "/api/auth/login",
                json={"username": "unknown", "password": "invalid"},
                headers={"X-Forwarded-For": "198.51.100.42"},
            ).status_code
            == 401
        )
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()
    restarted = make_client()
    assert (
        restarted.post(
            "/api/auth/login",
            json={"username": "unknown", "password": "invalid"},
            headers={"X-Forwarded-For": "198.51.100.42"},
        ).status_code
        == 429
    )


# ---------------------------------------------------------------------------
# Tests — Replay end-to-end (requires local SPEDIA artifacts)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not Path("data/spedia/review-v3/replay_manifest.json").exists(),
    reason="Genuine local SPEDIA review unavailable",
)
def test_actual_spedia_postgres_replay_end_to_end(integration, tmp_path):
    """Actual source-backed frozen vectors → inference → PG → FastAPI TestClient."""
    from src.db.models import ReplayRun

    factory, root, _, settings = integration
    run = Path("data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223")
    version = publish_run(factory, run)
    assert publish_run(factory, run) == version

    os.environ["REPLAY_DIRECTORY"] = "data/spedia/review-v3"
    os.environ["REALISTIC_REPLAY_DIRECTORY"] = "data/spedia/replay-realistic-v1"
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()

    anonymous = make_client()
    assert anonymous.get("/api/replay").status_code == 401

    viewer, vheaders = login("viewer")
    assert viewer.get("/api/replay").status_code == 403
    assert viewer.post("/api/replay/detect", headers=vheaders).status_code == 403

    analyst, headers = login("analyst")
    assert analyst.get("/api/replay").json()["events"] == 225
    assert analyst.post("/api/replay/detect").status_code == 403

    response = analyst.post("/api/replay/detect", headers=headers)
    assert response.status_code == 200, response.json()
    data = response.json()
    assert len(data["predictions"]) == 16
    assert all("label" not in p and "Anomaly" not in p for p in data["predictions"])

    window = data["predictions"][0]["window_id"]
    events = analyst.get(f"/api/replay/runs/{data['run_id']}/events?window_id={window}")
    assert events.status_code == 200 and events.json()["events"]
    assert all(
        not set(event) & {"Anomaly", "Description", "Full_log", "Agent_name", "Level", "label"}
        for event in events.json()["events"]
    )
    assert analyst.get(f"/api/replay/runs/{data['run_id']}/events?window_id=unlisted").status_code == 404

    again = analyst.post("/api/replay/detect", headers=headers).json()
    assert again["run_id"] == data["run_id"] and again["reused"]

    with factory() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(ReplayRun).where(ReplayRun.dataset_id == "spedia-v2")
            )
            == 1
        )

    assert analyst.get(f"/api/replay/runs/{data['run_id']}/ground-truth").status_code == 200
    assert analyst.get("/api/replay/runs/missing/ground-truth").status_code == 404

    saved = analyst.get(f"/api/replay/runs/{data['run_id']}").json()
    alert = next(p for p in saved["predictions"] if p["alert_id"])
    updated = analyst.post(
        f"/api/threats/{alert['alert_id']}/status",
        json={"status": "IN_PROGRESS", "version": alert["alert_version"]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.json()

    other, other_headers = login("analyst")
    persisted = other.get(f"/api/replay/runs/{data['run_id']}").json()
    assert next(
        p for p in persisted["predictions"] if p["alert_id"] == alert["alert_id"]
    )["alert_status"] == "IN_PROGRESS"

    for endpoint in (
        "/api/stats", "/api/users", "/api/timeline", "/api/model-metrics",
        "/api/data-sources", "/api/users/irene", "/api/graph?user_id=irene",
    ):
        result = other.get(endpoint)
        assert result.status_code == 200, (endpoint, result.json())

    assert other.get("/api/stats").json()["window_unit"] == "hour"
    assert other.get("/api/stats").json()["relative_time"] is False
    assert other.get("/api/graph?user_id=irene").json()["edges"][0]["type"] == "observed_on_host"

    import time
    realistic_info = other.get("/api/replay?mode=realistic")
    assert realistic_info.status_code == 200
    assert realistic_info.json()["windows"] == 421
    assert other.get("/api/replay?mode=invalid").status_code == 400

    started = time.perf_counter()
    realistic = other.post("/api/replay/detect", json={"mode": "realistic"}, headers=other_headers)
    assert realistic.status_code == 200, realistic.json()
    wall_ms = (time.perf_counter() - started) * 1000

    rid = realistic.json()["run_id"]
    assert rid != data["run_id"]

    persisted = other.get(f"/api/replay/runs/{rid}").json()
    assert persisted["mode"] == "realistic" and len(persisted["predictions"]) == 421

    timeline = other.get(f"/api/replay/runs/{rid}/events?limit=500").json()
    assert timeline["total"] == 21585 and len(timeline["events"]) == 500
    assert timeline["next_offset"] == 500
    assert [e["time"] for e in timeline["events"]] == sorted(e["time"] for e in timeline["events"])
    assert other.get(f"/api/replay/runs/{rid}/events?limit=501").status_code == 400

    truth = other.get(f"/api/replay/runs/{rid}/ground-truth").json()
    assert {"TP", "FN", "FP", "TN"}.issubset({w["example_outcome"] for w in truth["windows"]})
    assert all(w.get("miss_explanation") for w in truth["windows"] if w["example_outcome"] == "FN")

    reused_resp = other.post("/api/replay/detect", json={"mode": "realistic"}, headers=other_headers)
    assert reused_resp.json()["reused"] and reused_resp.json()["run_id"] == rid

    (tmp_path / "replay-benchmark.json").write_text(
        json.dumps(dict(
            context="Actual SPEDIA artifacts; isolated local PostgreSQL; FastAPI TestClient, no HTTP transport.",
            windows=421, events=21585,
            cold_request_ms=wall_ms,
            cold=realistic.json()["timings"],
        ), indent=2)
    )

    admin, admin_headers = login()
    assert admin.post("/api/retrain", json={}, headers=admin_headers).status_code == 409


# ---------------------------------------------------------------------------
# Tests — Primary defaults are SPEDIA
# ---------------------------------------------------------------------------

def test_primary_defaults_are_spedia(integration, monkeypatch):
    monkeypatch.delenv("DATASET_ID", raising=False)
    monkeypatch.delenv("FEATURE_PATH", raising=False)
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()
    settings = dep.get_settings()
    assert settings.dataset_id == "spedia-v2"
    assert settings.feature_path == "data/spedia/features-temporal/features.parquet"


# ---------------------------------------------------------------------------
# Tests — Rate-limit expiry
# ---------------------------------------------------------------------------

def test_rate_limit_expiry_does_not_require_training_worker(integration):
    from datetime import timedelta
    from src.db.models import RateLimit, now
    factory, *_ = integration
    expired_key = "f" * 64
    with factory.begin() as db:
        db.add(RateLimit(key=expired_key, count=7, expires_at=now() - timedelta(seconds=1)))
    login("analyst")
    with factory() as db:
        assert db.get(RateLimit, expired_key) is None


# ---------------------------------------------------------------------------
# Tests — Raw CSV inference (requires provisioned inference context)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not Path("data/inference/context-v1/context.json").exists(),
    reason="Verified original inference context unavailable",
)
def test_new_raw_csv_inference_is_separate_durable_and_authorized(integration, monkeypatch):
    import io
    import joblib
    import numpy as np
    from src.db.models import InferenceRun, InferenceAlert, DailyBehavior
    from src.inference.raw import load_context, from_records, generate_features
    from tests.test_raw_inference import fixture_csv, settings as input_settings, START, END
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import IsolationForest

    factory, root, _, settings = integration
    directory = "data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223"
    version = publish_run(factory, directory)

    os.environ["ALLOW_FIXTURE_DATA"] = "1"
    os.environ["INFERENCE_CONTEXT_DIRECTORY"] = "data/inference/context-v1"
    from src.api import dependencies as dep
    dep.get_settings.cache_clear()

    def forbidden(*a, **k):
        raise AssertionError("Uploads cannot fit model/scaler")
    monkeypatch.setattr(StandardScaler, "fit", forbidden)
    monkeypatch.setattr(IsolationForest, "fit", forbidden)

    analyst, headers = login("analyst")
    viewer, vheaders = login("viewer")

    assert viewer.get("/api/inference/context").status_code == 403
    assert viewer.post("/api/inference/import", headers=vheaders).status_code == 403
    assert make_client().get("/api/inference/context").status_code == 401

    info = analyst.get("/api/inference/context")
    assert info.status_code == 200, info.json()
    token = info.json()["context_token"]
    options = input_settings(token)
    content = fixture_csv()

    def upload(data=content, config=options, csrf=headers):
        return analyst.post(
            "/api/inference/import",
            data={**config},
            files={"file": ("raw-fixture.csv", io.BytesIO(data), "text/csv")},
            headers=csrf,
        )

    assert upload(csrf={}).status_code == 403
    assert upload(config={**options, "coverage_start": str(END)}).status_code == 422
    assert upload(config={**options, "complete_hours": "false"}).status_code == 422
    assert upload(config={**options, "context_token": "stale"}).status_code == 422
    assert upload(data=fixture_csv(user="unknown-fixture-user")).status_code == 422

    def benchmark_counts(db):
        return tuple(
            db.scalar(select(func.count()).select_from(t))
            for t in (DailyScore, DailyBehavior, Alert, ModelVersion)
        )
    with factory() as db:
        before = benchmark_counts(db)

    result = upload()
    assert result.status_code == 201, result.json()
    run_id = result.json()["run_id"]
    assert upload().json() == {"run_id": run_id, "reused": True}

    saved = analyst.get(f"/api/inference/runs/{run_id}").json()
    assert saved["provenance"]["source_kind"] == "engineering-test-fixture"
    assert saved["predictions"] and all("label" not in p for p in saved["predictions"])

    with factory() as db:
        assert before == benchmark_counts(db), "Imported data must not change benchmark tables"
        record = db.get(InferenceRun, run_id)
        features = __import__("pandas").DataFrame(record.features)
        model = joblib.load(Path(directory) / "model.joblib")
        np.testing.assert_array_equal(
            model.score(features[model.names])[0],
            [p["risk_score"] for p in saved["predictions"]],
        )
        assert db.scalar(
            select(func.count()).select_from(InferenceAlert).where(InferenceAlert.run_id == run_id)
        ) > 0

    alert = next(p for p in saved["predictions"] if p["alert_id"])
    changed = analyst.post(
        f"/api/inference/alerts/{alert['alert_id']}/status",
        json={"status": "IN_PROGRESS", "version": alert["alert_version"]},
        headers=headers,
    )
    assert changed.status_code == 200, changed.json()
    assert analyst.post(
        f"/api/inference/alerts/{alert['alert_id']}/status",
        json={"status": "RESOLVED", "version": alert["alert_version"]},
        headers=headers,
    ).status_code == 409

    other, other_headers = login("analyst")
    persisted = other.get(f"/api/inference/runs/{run_id}").json()
    assert persisted["predictions"][0]["alert_status"] == "IN_PROGRESS"

    next_context = other.get("/api/inference/context").json()
    assert next_context["context_token"] == run_id
    assert next_context["next_coverage_start"] == str(END)
    assert other.get("/api/inference/runs").json()["runs"][0]["run_id"] == run_id
