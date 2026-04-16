"""
Isolation Forest Anomaly Detection Model
==========================================
Primary unsupervised model. Trains on normal behavior,
scores all users, outputs anomaly scores 0-1.

Why Isolation Forest?
  - No labels required (unsupervised)
  - Scales to millions of events
  - Naturally handles high-dimensional feature spaces
  - Industry-standard for UEBA (used by Splunk, IBM QRadar)
"""

import numpy as np
import pandas as pd
import os
import yaml
import joblib
import logging
import json
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score, classification_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class IsolationForestDetector:
    """
    Wrapper around sklearn IsolationForest with:
      - Configurable hyperparameters
      - Anomaly score normalization to [0, 100]
      - Evaluation against ground truth
      - Persistence (save/load)
    """

    def __init__(self, config_path="config.yaml"):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)
        self.params = self.cfg["models"]["isolation_forest"]
        self.model_dir = self.cfg["paths"]["models"]
        os.makedirs(self.model_dir, exist_ok=True)
        self.model = None
        self.score_min = None
        self.score_max = None

    def build(self):
        """Instantiate IsolationForest with config params."""
        self.model = IsolationForest(
            n_estimators=self.params["n_estimators"],
            contamination=self.params["contamination"],
            max_samples=self.params["max_samples"],
            random_state=self.params["random_state"],
            n_jobs=self.params["n_jobs"],
        )
        return self.model

    def train(self, X_train):
        """
        Fit the model on training data.
        IsolationForest learns what 'normal' looks like.
        The contamination parameter tells it ~5% of training data may be anomalies.
        """
        logger.info(f"Training Isolation Forest on {X_train.shape[0]:,} samples, "
                    f"{X_train.shape[1]} features...")
        if self.model is None:
            self.build()

        self.model.fit(X_train)

        # Calibrate score range on training data
        raw_scores = self.model.score_samples(X_train)
        self.score_min = raw_scores.min()
        self.score_max = raw_scores.max()

        logger.info("Training complete.")
        logger.info(f"  Raw score range: [{self.score_min:.4f}, {self.score_max:.4f}]")
        return self

    def predict_scores(self, X):
        """
        Return normalized anomaly scores in [0, 100].
        Higher score = MORE anomalous = higher threat.

        IsolationForest's score_samples returns negative values:
          more negative = more anomalous
        We invert and normalize to [0, 100].
        """
        raw = self.model.score_samples(X)
        # Invert: lower (more negative) raw → higher anomaly score
        normalized = 1 - (raw - self.score_min) / (self.score_max - self.score_min + 1e-10)
        return np.clip(normalized * 100, 0, 100)

    def predict_labels(self, X):
        """
        Return -1 (anomaly) or 1 (normal) per IsolationForest convention.
        """
        return self.model.predict(X)

    def evaluate(self, X, ground_truth_df, meta_df):
        """
        Evaluate model against ground truth labels (if available).
        Computes per-user average anomaly score and compares to known insiders.
        """
        if ground_truth_df is None or ground_truth_df.empty:
            logger.info("No ground truth available for evaluation.")
            return {}

        scores = self.predict_scores(X)
        meta = meta_df.copy()
        meta["if_score"] = scores

        # Average score per user
        user_scores = meta.groupby("user")["if_score"].mean().reset_index()
        user_scores.columns = ["user_id", "avg_score"]

        # Merge with ground truth
        gt = ground_truth_df[["user_id", "is_insider"]].drop_duplicates()
        merged = user_scores.merge(gt, on="user_id", how="inner")

        if merged["is_insider"].sum() == 0:
            logger.warning("No positive cases in ground truth for evaluation.")
            return {}

        y_true = merged["is_insider"].astype(int).values
        y_score = merged["avg_score"].values

        try:
            auc = roc_auc_score(y_true, y_score)
            logger.info(f"Isolation Forest AUC-ROC: {auc:.4f}")
        except Exception as e:
            logger.warning(f"AUC computation failed: {e}")
            auc = None

        # Top-K precision
        k = max(1, int(y_true.sum()))
        top_k = merged.nlargest(k, "avg_score")["is_insider"].mean()
        logger.info(f"Top-{k} Precision: {top_k:.4f}")

        return {"auc_roc": auc, f"top_{k}_precision": top_k}

    def save(self, suffix=""):
        """Save model and calibration data."""
        path = os.path.join(self.model_dir, f"isolation_forest{suffix}.pkl")
        meta = {
            "score_min": float(self.score_min),
            "score_max": float(self.score_max),
            "params": self.params,
        }
        joblib.dump({"model": self.model, "meta": meta}, path)
        logger.info(f"Isolation Forest saved → {path}")
        return path

    def load(self, suffix=""):
        """Load saved model."""
        path = os.path.join(self.model_dir, f"isolation_forest{suffix}.pkl")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model not found: {path}")
        bundle = joblib.load(path)
        self.model = bundle["model"]
        self.score_min = bundle["meta"]["score_min"]
        self.score_max = bundle["meta"]["score_max"]
        logger.info(f"Isolation Forest loaded ← {path}")
        return self


if __name__ == "__main__":
    # Quick test
    X_train = np.load("data/models/X_train.npy")
    X_all = np.load("data/models/X_all.npy")

    detector = IsolationForestDetector()
    detector.train(X_train)
    scores = detector.predict_scores(X_all)
    print(f"Score distribution: min={scores.min():.1f}, mean={scores.mean():.1f}, "
          f"max={scores.max():.1f}, p95={np.percentile(scores, 95):.1f}")
    detector.save()
