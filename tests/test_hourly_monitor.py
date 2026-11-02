"""Hourly API scope, missing-hour semantics and existing-alert integration."""
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from src.api import main
from src.api.dependencies import Settings, get_active_model, get_db, get_settings


def score(user, hour, value, tier, model="v6"):
    return SimpleNamespace(user=user, relative_day=hour, risk_score=value, risk_tier=tier,
                           model_version=model, components={"if_score": value, "neural_score": value},
                           explanation={"window_start": f"2025-03-06 {hour:02}:00:00", "event_count": 3})


@pytest.fixture
def hourly_client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/test")
    monkeypatch.setattr(main, "_get_factory", lambda: None)
    model = SimpleNamespace(id="v6", dataset_id="spedia-v2", report={
        "dataset": {"time_origin": "2025-03-06 00:00:00"}, "display_name": "SPEDIA V6 Maximum",
        "calibration": {"high_threshold": 97.72, "tier_thresholds": [39, 78, 97.72, 98.86]}})
    alert = SimpleNamespace(id="alert-3", severity="CRITICAL", status="OPEN", version=1, created_at=datetime(2025, 3, 6))
    stored = [(score("alice", 3, 20, "NORMAL"), None),
              (score("bob", 3, 99, "CRITICAL"), alert),
              (score("alice", 4, 100, "CRITICAL"), None),
              (score("outside-model", 3, 100, "CRITICAL", "old"), None)]

    class Result(list):
        def all(self):
            return list(self)

        def mappings(self):
            return self

    class Database:
        statements = []

        def scalar(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            self.statements.append((str(compiled), compiled.params))
            return 4 if "max(" in str(compiled) else 1

        def execute(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            self.statements.append((str(compiled), compiled.params))
            if "GROUP BY" in str(compiled):
                return Result([dict(window_index=3, observed_accounts=2, average_risk=59.5,
                                    peak_risk=99, alerts=1, open_alerts=1),
                               dict(window_index=4, observed_accounts=1, average_risk=100,
                                    peak_risk=100, alerts=0, open_alerts=0)])
            hour = next((value for key, value in compiled.params.items() if key.startswith("relative_day")), None)
            assert "v6" in compiled.params.values(), "Queries must scope the active model"
            rows = [(s, a) for s, a in stored if s.model_version == "v6" and (hour is None or s.relative_day == hour)]
            if statement.column_descriptions[0]["name"] == "Alert":
                return Result([(a, s) for s, a in rows if a is not None])
            return Result(rows)

        def add(self, record):
            pass

        def commit(self):
            pass

    db = Database()
    settings = Settings()
    app = main.create_app(settings)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_active_model] = lambda: model
    with TestClient(app) as client:
        yield client, db


def test_hour_detail_does_not_use_user_historical_peak(hourly_client):
    client, _ = hourly_client
    response = client.get("/api/hours/3")
    assert response.status_code == 200
    data = response.json()
    assert data["observed_accounts"] == 2
    assert data["observed_events"] == 6
    assert data["tier_distribution"]["NORMAL"] == 1
    assert data["tier_distribution"]["CRITICAL"] == 1
    assert next(row for row in data["observations"] if row["user"] == "alice")["risk_score"] == 20
    assert data["window_start"] == "2025-03-06 03:00:00"
    assert data["window_end"] == "2025-03-06 04:00:00"
    assert data["alerts"][0]["alert_id"] == "alert-3"
    assert data["open_alerts"] == 1


def test_missing_hour_is_not_a_normal_classification(hourly_client):
    client, _ = hourly_client
    response = client.get("/api/hours/5")
    assert response.status_code == 404
    assert "absence is not a normal" in response.json()["error"]


def test_hour_list_preserves_real_observation_membership(hourly_client):
    client, _ = hourly_client
    data = client.get("/api/hours?days=7").json()
    assert [row["window_index"] for row in data["hours"]] == [3, 4]
    assert data["latest_window_index"] == 4
    assert data["hours"][0]["peak_tier"] == "CRITICAL"
    assert "Missing hours are unobserved" in data["time_basis"]


@pytest.mark.parametrize("value", ["-1", "", "1.2", "not-an-hour", "９", "9999999999"])
def test_alert_hour_filter_rejects_invalid_values(hourly_client, value):
    client, _ = hourly_client
    assert client.get("/api/threats", params={"hour": value}).status_code == 400


def test_hour_filter_applies_to_alert_list_and_export(hourly_client):
    client, db = hourly_client
    for path in ("/api/threats?hour=3", "/api/export?kind=alerts&hour=3"):
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        rows = data.get("alerts", data.get("records"))
        assert len(rows) == 1
        assert rows[0]["relative_day"] == 3
        assert rows[0]["alert_id"] == "alert-3"
        assert data["window_index"] == 3
    assert any("relative_day =" in sql and 3 in params.values() for sql, params in db.statements)
