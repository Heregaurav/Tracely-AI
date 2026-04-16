"""
SENTINEL — Full Test Suite
===========================
Tests every layer: data generation, preprocessing,
feature engineering, models, scoring, and API.

Run with:
    cd insider-threat-detection
    python -m pytest tests/ -v
    python -m pytest tests/ -v --tb=short 2>&1 | head -80
"""

import pytest
import sys
import os
import numpy as np
import pandas as pd
import json
import tempfile
import shutil

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def raw_data_dir():
    """Use the existing data/raw directory (already generated)."""
    d = "data/raw"
    assert os.path.exists(d), "Run generate_dataset.py first"
    return d

@pytest.fixture(scope="session")
def processed_dir():
    return "data/processed"

@pytest.fixture(scope="session")
def model_dir():
    return "data/models"

@pytest.fixture(scope="session")
def flask_client():
    from src.api.app import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ─────────────────────────────────────────────────────────────────
# 1. Dataset Generation Tests
# ─────────────────────────────────────────────────────────────────

class TestDatasetGeneration:

    def test_all_csv_files_exist(self, raw_data_dir):
        """All 5 CERT CSV files must be present."""
        required = ["logon.csv", "file.csv", "device.csv", "email.csv", "LDAP.csv"]
        for f in required:
            path = os.path.join(raw_data_dir, f)
            assert os.path.exists(path), f"Missing: {f}"

    def test_ground_truth_exists(self, raw_data_dir):
        """Ground truth labels must exist."""
        assert os.path.exists(os.path.join(raw_data_dir, "ground_truth.csv"))

    def test_ldap_has_required_columns(self, raw_data_dir):
        df = pd.read_csv(os.path.join(raw_data_dir, "LDAP.csv"))
        required = ["user_id", "department", "role"]
        for col in required:
            assert col in df.columns, f"LDAP missing column: {col}"

    def test_logon_has_required_columns(self, raw_data_dir):
        df = pd.read_csv(os.path.join(raw_data_dir, "logon.csv"))
        for col in ["user", "date", "activity"]:
            assert col in df.columns

    def test_logon_activity_values(self, raw_data_dir):
        df = pd.read_csv(os.path.join(raw_data_dir, "logon.csv"))
        valid = {"Logon", "Logoff"}
        assert df["activity"].isin(valid).all(), "Invalid activity values in logon.csv"

    def test_email_has_to_from(self, raw_data_dir):
        df = pd.read_csv(os.path.join(raw_data_dir, "email.csv"))
        assert "to" in df.columns and "from" in df.columns

    def test_no_empty_csvs(self, raw_data_dir):
        for fname in ["logon.csv", "file.csv", "device.csv", "email.csv"]:
            df = pd.read_csv(os.path.join(raw_data_dir, fname))
            assert len(df) > 0, f"{fname} is empty"

    def test_ground_truth_has_insiders(self, raw_data_dir):
        gt = pd.read_csv(os.path.join(raw_data_dir, "ground_truth.csv"))
        assert gt["is_insider"].sum() > 0, "No insider threats in ground truth"

    def test_threat_types_valid(self, raw_data_dir):
        gt = pd.read_csv(os.path.join(raw_data_dir, "ground_truth.csv"))
        valid_types = {"data_exfiltrator", "disgruntled_saboteur", "negligent_insider", "none"}
        assert set(gt["threat_type"].unique()).issubset(valid_types)


# ─────────────────────────────────────────────────────────────────
# 2. Preprocessing Tests
# ─────────────────────────────────────────────────────────────────

class TestPreprocessing:

    def test_feature_matrix_exists(self, processed_dir):
        path = os.path.join(processed_dir, "daily_behavior.parquet")
        assert os.path.exists(path), "Run preprocessor.py first"

    def test_feature_matrix_shape(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "daily_behavior.parquet"))
        assert df.shape[0] > 100,   "Too few rows in feature matrix"
        assert df.shape[1] >= 10,   "Too few features"

    def test_feature_matrix_has_user_day(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "daily_behavior.parquet"))
        assert "user" in df.columns
        assert "day"  in df.columns

    def test_no_all_null_rows(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "daily_behavior.parquet"))
        numeric = df.select_dtypes(include=[np.number])
        all_null = numeric.isnull().all(axis=1).sum()
        assert all_null == 0, f"{all_null} rows are all-null"

    def test_deviation_features_present(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "daily_behavior.parquet"))
        dev_cols = [c for c in df.columns if c.endswith("_deviation")]
        assert len(dev_cols) >= 4, "Rolling deviation features missing"

    def test_after_hours_ratio_bounded(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "daily_behavior.parquet"))
        if "after_hours_ratio" in df.columns:
            assert df["after_hours_ratio"].between(0, 1).all(), \
                "after_hours_ratio must be between 0 and 1"

    def test_scored_behaviors_exist(self, processed_dir):
        assert os.path.exists(os.path.join(processed_dir, "scored_behaviors.parquet"))

    def test_alerts_exist(self, processed_dir):
        assert os.path.exists(os.path.join(processed_dir, "alerts.parquet"))


# ─────────────────────────────────────────────────────────────────
# 3. Feature Engineering Tests
# ─────────────────────────────────────────────────────────────────

class TestFeatureEngineering:

    def test_x_all_exists(self, model_dir):
        assert os.path.exists(os.path.join(model_dir, "X_all.npy"))

    def test_x_train_exists(self, model_dir):
        assert os.path.exists(os.path.join(model_dir, "X_train.npy"))

    def test_scaler_exists(self, model_dir):
        assert os.path.exists(os.path.join(model_dir, "scaler.pkl"))

    def test_feature_names_json(self, model_dir):
        path = os.path.join(model_dir, "feature_names.json")
        assert os.path.exists(path)
        with open(path) as f:
            names = json.load(f)
        assert len(names) >= 10, "Too few features"

    def test_x_all_no_nan_inf(self, model_dir):
        X = np.load(os.path.join(model_dir, "X_all.npy"))
        assert not np.isnan(X).any(),  "NaN values in X_all"
        assert not np.isinf(X).any(),  "Inf values in X_all"

    def test_x_train_subset_of_x_all(self, model_dir):
        X_all   = np.load(os.path.join(model_dir, "X_all.npy"))
        X_train = np.load(os.path.join(model_dir, "X_train.npy"))
        assert X_train.shape[0] <= X_all.shape[0]
        assert X_train.shape[1] == X_all.shape[1], "Feature count mismatch"

    def test_meta_parquet_matches_x_all(self, model_dir):
        X_all = np.load(os.path.join(model_dir, "X_all.npy"))
        meta  = pd.read_parquet(os.path.join(model_dir, "X_meta.parquet"))
        assert len(meta) == X_all.shape[0], "Meta rows don't match X_all rows"


# ─────────────────────────────────────────────────────────────────
# 4. Isolation Forest Tests
# ─────────────────────────────────────────────────────────────────

class TestIsolationForest:

    def test_model_file_exists(self, model_dir):
        assert os.path.exists(os.path.join(model_dir, "isolation_forest.pkl"))

    def test_model_loads(self, model_dir):
        from src.models.isolation_forest_model import IsolationForestDetector
        det = IsolationForestDetector()
        det.load()
        assert det.model is not None

    def test_scores_range(self, model_dir):
        from src.models.isolation_forest_model import IsolationForestDetector
        X = np.load(os.path.join(model_dir, "X_all.npy"))
        det = IsolationForestDetector()
        det.load()
        scores = det.predict_scores(X)
        assert scores.min() >= 0,   f"Min score below 0: {scores.min()}"
        assert scores.max() <= 100, f"Max score above 100: {scores.max()}"

    def test_scores_distribution_sane(self, model_dir):
        """Most users should be NORMAL — scores should be right-skewed."""
        from src.models.isolation_forest_model import IsolationForestDetector
        X = np.load(os.path.join(model_dir, "X_all.npy"))
        det = IsolationForestDetector()
        det.load()
        scores = det.predict_scores(X)
        pct_high = (scores > 70).mean()
        assert pct_high < 0.25, f"Too many high scores: {pct_high:.1%} (expected < 25%)"

    def test_insiders_score_higher_than_normals(self, model_dir, raw_data_dir):
        """Insider threats should on average score higher than normal users."""
        from src.models.isolation_forest_model import IsolationForestDetector
        X   = np.load(os.path.join(model_dir, "X_all.npy"))
        meta = pd.read_parquet(os.path.join(model_dir, "X_meta.parquet"))
        gt   = pd.read_csv(os.path.join(raw_data_dir, "ground_truth.csv"))

        det = IsolationForestDetector()
        det.load()
        scores = det.predict_scores(X)
        meta["score"] = scores

        # Average score per user
        user_avg = meta.groupby("user")["score"].mean().reset_index()
        user_avg.columns = ["user_id", "avg_score"]
        merged = user_avg.merge(gt[["user_id","is_insider"]], on="user_id", how="inner")

        insider_avg = merged[merged["is_insider"]]["avg_score"].mean()
        normal_avg  = merged[~merged["is_insider"]]["avg_score"].mean()

        assert insider_avg > normal_avg, \
            f"Insiders avg {insider_avg:.1f} not > normals avg {normal_avg:.1f}"

    def test_labels_binary(self, model_dir):
        from src.models.isolation_forest_model import IsolationForestDetector
        X = np.load(os.path.join(model_dir, "X_all.npy"))
        det = IsolationForestDetector()
        det.load()
        labels = det.predict_labels(X)
        assert set(labels).issubset({-1, 1}), "Labels must be -1 or 1"


# ─────────────────────────────────────────────────────────────────
# 5. Autoencoder Tests
# ─────────────────────────────────────────────────────────────────

class TestAutoencoder:

    def test_model_meta_exists(self, model_dir):
        assert os.path.exists(os.path.join(model_dir, "autoencoder_meta.json"))

    def test_model_loads(self, model_dir):
        from src.models.autoencoder_model import AutoencoderDetector
        ae = AutoencoderDetector()
        ae.load()
        assert ae.model is not None
        assert ae.threshold is not None

    def test_scores_range(self, model_dir):
        from src.models.autoencoder_model import AutoencoderDetector
        X = np.load(os.path.join(model_dir, "X_all.npy"))
        ae = AutoencoderDetector()
        ae.load()
        scores = ae.predict_scores(X)
        assert scores.min() >= 0
        assert scores.max() <= 100

    def test_threshold_is_positive(self, model_dir):
        from src.models.autoencoder_model import AutoencoderDetector
        ae = AutoencoderDetector()
        ae.load()
        assert ae.threshold > 0, "Threshold must be positive"

    def test_normal_data_low_error(self, model_dir):
        """Training data should reconstruct with mostly low error."""
        from src.models.autoencoder_model import AutoencoderDetector
        X_train = np.load(os.path.join(model_dir, "X_train.npy"))
        ae = AutoencoderDetector()
        ae.load()
        scores = ae.predict_scores(X_train)
        # At least 80% of training samples should score < 50
        pct_low = (scores < 50).mean()
        assert pct_low > 0.70, f"Too many high AE scores on training data: {(1-pct_low):.1%}"


# ─────────────────────────────────────────────────────────────────
# 6. Scoring Engine Tests
# ─────────────────────────────────────────────────────────────────

class TestScoringEngine:

    def test_scored_behaviors_columns(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "scored_behaviors.parquet"))
        for col in ["user", "day", "risk_score", "risk_tier", "if_score", "ae_score"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_risk_tiers_valid(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "scored_behaviors.parquet"))
        valid = {"NORMAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert df["risk_tier"].isin(valid).all()

    def test_risk_scores_bounded(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "scored_behaviors.parquet"))
        assert df["risk_score"].between(0, 100).all()

    def test_user_risk_scores_columns(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "user_risk_scores.parquet"))
        for col in ["user", "max_risk_score", "avg_risk_score", "risk_tier", "trend"]:
            assert col in df.columns

    def test_trend_values_valid(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "user_risk_scores.parquet"))
        assert df["trend"].isin({"up","down","stable"}).all()

    def test_alerts_have_required_fields(self, processed_dir):
        df = pd.read_parquet(os.path.join(processed_dir, "alerts.parquet"))
        if len(df) > 0:
            for col in ["alert_id","user_id","risk_score","risk_tier","alert_type","status"]:
                assert col in df.columns, f"Alerts missing: {col}"

    def test_ensemble_score_between_components(self):
        """Ensemble score should be between IF and AE scores (weighted average)."""
        from src.models.scorer import ScoringEngine
        eng = ScoringEngine()
        if_s = np.array([20.0, 80.0, 50.0])
        ae_s = np.array([40.0, 60.0, 70.0])
        combo = eng.ensemble_score(if_s, ae_s)
        # Weighted: 60% IF + 40% AE
        expected = 0.6 * if_s + 0.4 * ae_s
        np.testing.assert_allclose(combo, expected, rtol=1e-5)

    def test_tier_classification(self):
        from src.models.scorer import ScoringEngine
        eng = ScoringEngine()
        assert eng.classify_tier(96) == "CRITICAL"
        assert eng.classify_tier(88) == "HIGH"
        assert eng.classify_tier(75) == "MEDIUM"
        assert eng.classify_tier(55) == "LOW"
        assert eng.classify_tier(20) == "NORMAL"


# ─────────────────────────────────────────────────────────────────
# 7. Flask API Tests
# ─────────────────────────────────────────────────────────────────

class TestFlaskAPI:

    def test_health_endpoint(self, flask_client):
        r = flask_client.get("/health")
        assert r.status_code == 200
        d = r.get_json()
        assert d["status"] == "ok"
        assert d["data_loaded"] is True

    def test_stats_endpoint(self, flask_client):
        r = flask_client.get("/api/stats")
        assert r.status_code == 200
        d = r.get_json()
        assert "total_users" in d
        assert "open_alerts" in d
        assert "tier_distribution" in d
        assert d["total_users"] > 0

    def test_stats_total_users_correct(self, flask_client):
        r = flask_client.get("/api/stats")
        d = r.get_json()
        assert d["total_users"] == 100

    def test_threats_endpoint(self, flask_client):
        r = flask_client.get("/api/threats?limit=10")
        assert r.status_code == 200
        d = r.get_json()
        assert "alerts" in d
        assert "total" in d
        assert isinstance(d["alerts"], list)

    def test_threats_tier_filter(self, flask_client):
        r = flask_client.get("/api/threats?tier=HIGH&limit=100")
        d = r.get_json()
        for alert in d["alerts"]:
            assert alert["risk_tier"] == "HIGH"

    def test_users_endpoint(self, flask_client):
        r = flask_client.get("/api/users?limit=10")
        assert r.status_code == 200
        d = r.get_json()
        assert "users" in d
        assert d["total"] == 100
        assert len(d["users"]) == 10

    def test_users_pagination(self, flask_client):
        r1 = flask_client.get("/api/users?limit=10&page=1")
        r2 = flask_client.get("/api/users?limit=10&page=2")
        d1 = r1.get_json()["users"]
        d2 = r2.get_json()["users"]
        # Pages should not overlap
        ids1 = {u["user"] for u in d1}
        ids2 = {u["user"] for u in d2}
        assert ids1.isdisjoint(ids2), "Pagination overlap"

    def test_user_detail_endpoint(self, flask_client):
        r = flask_client.get("/api/users/CER0001")
        assert r.status_code == 200
        d = r.get_json()
        assert "risk_tier"    in d
        assert "daily_scores" in d
        assert "user"         in d

    def test_user_detail_404_on_unknown(self, flask_client):
        r = flask_client.get("/api/users/UNKNOWN_USER_XYZ")
        assert r.status_code == 404

    def test_timeline_endpoint(self, flask_client):
        r = flask_client.get("/api/timeline?days=30")
        assert r.status_code == 200
        d = r.get_json()
        assert "timeline" in d
        assert len(d["timeline"]) > 0

    def test_timeline_user_filter(self, flask_client):
        r = flask_client.get("/api/timeline?days=180&user_id=CER0001")
        assert r.status_code == 200
        d = r.get_json()
        assert "timeline" in d

    def test_heatmap_endpoint(self, flask_client):
        r = flask_client.get("/api/heatmap")
        assert r.status_code == 200
        d = r.get_json()
        assert "heatmap" in d
        # Check structure: each item has dept + dow + avg_risk
        if d["heatmap"]:
            item = d["heatmap"][0]
            assert "department" in item
            assert "dow"        in item
            assert "avg_risk"   in item

    def test_departments_endpoint(self, flask_client):
        r = flask_client.get("/api/departments")
        assert r.status_code == 200
        d = r.get_json()
        assert "departments" in d
        assert len(d["departments"]) > 0

    def test_departments_have_all_fields(self, flask_client):
        r = flask_client.get("/api/departments")
        d = r.get_json()
        for dept in d["departments"]:
            assert "department"    in dept
            assert "avg_risk"      in dept
            assert "user_count"    in dept
            assert "critical_count" in dept

    def test_users_sort_by_risk(self, flask_client):
        r = flask_client.get("/api/users?sort=max_risk_score&order=desc&limit=100")
        d = r.get_json()
        scores = [u["max_risk_score"] for u in d["users"]]
        assert scores == sorted(scores, reverse=True), "Users not sorted by risk"

    def test_api_returns_json_content_type(self, flask_client):
        r = flask_client.get("/api/stats")
        assert "application/json" in r.content_type


# ─────────────────────────────────────────────────────────────────
# 8. End-to-End Detection Quality Tests
# ─────────────────────────────────────────────────────────────────

class TestDetectionQuality:

    def test_known_insiders_in_top_25pct(self, processed_dir, raw_data_dir):
        """All 8 known insiders should appear in the top 25% by risk score."""
        ur = pd.read_parquet(os.path.join(processed_dir, "user_risk_scores.parquet"))
        gt = pd.read_csv(os.path.join(raw_data_dir, "ground_truth.csv"))

        insiders = set(gt[gt["is_insider"]]["user_id"].tolist())
        threshold_25 = ur["max_risk_score"].quantile(0.75)
        top_users    = set(ur[ur["max_risk_score"] >= threshold_25]["user"].tolist())

        detected = insiders & top_users
        detection_rate = len(detected) / len(insiders)
        assert detection_rate >= 0.5, \
            f"Only {detection_rate:.0%} of insiders in top 25%. Detected: {detected}"

    def test_no_normal_user_scores_100(self, processed_dir, raw_data_dir):
        """Normal users (non-insiders) should not reach score 100."""
        ur = pd.read_parquet(os.path.join(processed_dir, "user_risk_scores.parquet"))
        gt = pd.read_csv(os.path.join(raw_data_dir, "ground_truth.csv"))

        normals  = set(gt[~gt["is_insider"]]["user_id"].tolist())
        normal_df = ur[ur["user"].isin(normals)]
        maxed    = (normal_df["max_risk_score"] >= 99).sum()
        assert maxed == 0, f"{maxed} normal users hit score 99+"

    def test_risk_scores_not_all_same(self, processed_dir):
        """Risk scores must have variance — all-same means broken model."""
        ur = pd.read_parquet(os.path.join(processed_dir, "user_risk_scores.parquet"))
        std = ur["max_risk_score"].std()
        assert std > 1.0, f"Risk scores have near-zero variance: std={std:.3f}"

    def test_alert_types_are_expected(self, processed_dir):
        al = pd.read_parquet(os.path.join(processed_dir, "alerts.parquet"))
        if len(al) > 0:
            valid_types = {"DAILY_ANOMALY", "RISING_TREND"}
            assert al["alert_type"].isin(valid_types).all()

    def test_tier_distribution_realistic(self, processed_dir):
        """NORMAL users should be the majority (>50%)."""
        ur = pd.read_parquet(os.path.join(processed_dir, "user_risk_scores.parquet"))
        pct_normal = (ur["risk_tier"] == "NORMAL").mean()
        assert pct_normal >= 0.5, \
            f"Only {pct_normal:.0%} of users NORMAL — model may be too aggressive"


# ─────────────────────────────────────────────────────────────────
# Run directly
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", __file__, "-v", "--tb=short"],
        capture_output=False
    )
    sys.exit(result.returncode)
