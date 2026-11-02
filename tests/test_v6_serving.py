"""Versioned V6 deployment must reproduce its frozen development result."""
import json
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api import main
from src.api.dependencies import Settings, get_active_model, get_db, get_settings
from src.data.spedia import FEATURE_NAMES, contract
from src.data.spedia_behavioral_v6 import NAMES
from src.models.v6_maximum import serving_contract

ROOT = Path("data/artifacts/spedia-v6-maximum-20261102")


def test_versioned_contract_preserves_base_and_feature_order():
    current = serving_contract()
    assert current["version"] == "spedia-behavioral-v6"
    assert current["window_seconds"] == 3600
    assert [f["name"] for f in current["features"]] == NAMES
    assert len(NAMES) == len(set(NAMES)) == 55
    assert NAMES[:30] == FEATURE_NAMES
    assert len(contract()["features"]) == 30


def test_packaged_v6_exact_validation_and_no_mutation():
    if not (ROOT / "model.joblib").exists():
        pytest.skip("Private frozen V6 publication assets required")
    model = joblib.load(ROOT / "model.joblib")
    frame = pd.read_parquet(ROOT / "scores.parquet")
    report = json.loads((ROOT / "metrics.json").read_text())
    before = joblib.hash(model)
    index, tiers, _ = model.score(frame[NAMES])
    assert joblib.hash(model) == before
    np.testing.assert_array_equal(index, frame.risk_score)
    np.testing.assert_array_equal(tiers, frame.risk_tier)
    assert report["primary_metrics"]["confusion_matrix"] == [[252, 3], [10, 67]]
    assert report["primary_evaluation"] == "validation"
    assert report["held_out_metrics"] == {}
    assert not hasattr(model, "fit")
    assert report["calibration"]["high_threshold"] == 97.72727272727273
    assert set(frame.risk_tier) == {"NORMAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
    with pytest.raises(ValueError, match="55-feature"):
        model.score(frame[FEATURE_NAMES])


def test_main_report_exposes_development_scope_without_a_fake_test(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/test")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(main, "_get_factory", lambda: None)
    settings = Settings()
    app = main.create_app(settings)
    primary = {"f1": 0.9115646258503401, "precision": 0.9571428571428572,
               "recall": 0.8701298701298701, "false_positive_rate": 3 / 255}
    report = {"display_name": "SPEDIA V6 Maximum", "primary_evaluation": "validation",
              "primary_metrics": primary, "held_out_metrics": {}, "is_fixture": False}
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_active_model] = lambda: SimpleNamespace(report=report)
    with TestClient(app) as client:
        response = client.get("/api/model-metrics")
        assert response.status_code == 200
        actual = response.json()
        assert actual["primary_metrics"] == primary
        assert actual["primary_evaluation"] == "validation"
        assert actual["held_out_metrics"] == {}
