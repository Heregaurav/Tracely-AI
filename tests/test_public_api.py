"""Verify public production access without a real database or credentials."""
from fastapi.testclient import TestClient

from src.api import main
from src.api.dependencies import Settings, get_actor, get_db, get_settings


def public_app(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/test")
    monkeypatch.setenv("APP_ENV", "production")
    for key in ("SESSION_SECRET", "OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "DEV_AUTH_USERS"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    monkeypatch.setattr(main, "_get_factory", lambda: None)
    app = main.create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    class DatabaseStub:
        def scalars(self, *args, **kwargs):
            return []

        def scalar(self, *args, **kwargs):
            return None

        def execute(self, *args, **kwargs):
            return None

        def get(self, *args, **kwargs):
            return None

    app.dependency_overrides[get_db] = lambda: DatabaseStub()
    return app


def test_production_starts_without_auth_configuration(monkeypatch):
    app = public_app(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/model-versions").json() == {"versions": []}
        assert not client.cookies
    assert not any(route.path.startswith("/api/auth/") for route in app.routes)
    assert get_actor() == "public"


def test_public_writes_keep_business_validation(monkeypatch):
    with TestClient(public_app(monkeypatch)) as client:
        response = client.post("/api/model-versions/unknown/activate")
        assert response.status_code == 404
        assert response.json()["error"] == "Model version not found"
        response = client.post("/api/retrain")
        assert response.status_code == 409
        assert "frozen" in response.json()["error"]


def test_public_reads_keep_model_availability_validation(monkeypatch):
    with TestClient(public_app(monkeypatch)) as client:
        response = client.get("/api/stats")
        assert response.status_code == 503
        assert "No active model" in response.json()["error"]
