"""
Feature Engineering Module
============================
Takes the daily_behavior parquet, selects and transforms features
for ML input, handles encoding, scaling, and outputs:
  - X_train.npy  : feature matrix for training
  - X_all.npy    : full feature matrix for inference
  - scaler.pkl   : fitted StandardScaler
  - feature_names.json
"""

import pandas as pd
import numpy as np
import os
import json
import yaml
import joblib
import logging
from sklearn.preprocessing import StandardScaler, LabelEncoder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


FEATURE_COLS = [
    # --- Login behavior ---
    "login_count",
    "login_hour_mean",
    "login_hour_std",
    "after_hours_logins",
    "after_hours_ratio",
    "unique_pcs",

    # --- Session behavior ---
    "session_duration_total",
    "session_count",

    # --- File behavior ---
    "files_accessed",
    "files_after_hours",
    "sensitive_files",
    "files_per_session",

    # --- USB / device behavior ---
    "usb_count",
    "usb_after_hours",

    # --- Email behavior ---
    "emails_sent",
    "emails_external",
    "email_attachments",

    # --- Temporal ---
    "day_of_week",
    "is_weekend",

    # --- Rolling deviation features (most informative for anomaly detection) ---
    "files_accessed_deviation",
    "usb_count_deviation",
    "emails_external_deviation",
    "after_hours_ratio_deviation",
    "sensitive_files_deviation",
    "email_attachments_deviation",
    "session_duration_total_deviation",
]


class FeatureEngineer:
    """
    Selects, encodes, and scales features for ML training and inference.
    """

    def __init__(self, config_path="config.yaml"):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)
        self.proc_dir = self.cfg["paths"]["processed_data"]
        self.model_dir = self.cfg["paths"]["models"]
        os.makedirs(self.model_dir, exist_ok=True)
        self.scaler = StandardScaler()
        self.dept_encoder = LabelEncoder()
        self.feature_cols = None

    def load_features(self):
        path = os.path.join(self.proc_dir, "daily_behavior.parquet")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Feature matrix not found at {path}. Run preprocessor first.")
        df = pd.read_parquet(path)
        logger.info(f"Loaded feature matrix: {df.shape}")
        return df

    def select_and_encode(self, df):
        """Select available feature columns, encode categoricals."""
        available = [c for c in FEATURE_COLS if c in df.columns]
        missing = [c for c in FEATURE_COLS if c not in df.columns]
        if missing:
            logger.warning(f"Missing features (will be filled with 0): {missing}")
            for c in missing:
                df[c] = 0

        # Encode department if present
        if "department" in df.columns:
            df["dept_encoded"] = self.dept_encoder.fit_transform(
                df["department"].fillna("Unknown")
            )
            available.append("dept_encoded")

        self.feature_cols = available
        X = df[available].copy()

        # Handle infinities and extreme outliers
        X = X.replace([np.inf, -np.inf], np.nan)
        for col in X.columns:
            col_std = X[col].std()
            if col_std > 0:
                X[col] = X[col].clip(
                    lower=X[col].mean() - 5 * col_std,
                    upper=X[col].mean() + 5 * col_std,
                )
        X = X.fillna(0)

        logger.info(f"Feature set: {len(available)} features")
        return X

    def fit_transform(self, X):
        """Fit scaler and transform."""
        X_scaled = self.scaler.fit_transform(X)
        # Save scaler and feature names
        joblib.dump(self.scaler, os.path.join(self.model_dir, "scaler.pkl"))
        with open(os.path.join(self.model_dir, "feature_names.json"), "w") as f:
            json.dump(self.feature_cols, f, indent=2)
        logger.info(f"Scaler fitted and saved. Feature matrix: {X_scaled.shape}")
        return X_scaled

    def transform(self, X):
        """Transform using already-fitted scaler."""
        scaler_path = os.path.join(self.model_dir, "scaler.pkl")
        if not hasattr(self.scaler, "mean_"):
            self.scaler = joblib.load(scaler_path)
        X_scaled = self.scaler.transform(X)
        return X_scaled

    def run(self):
        df = self.load_features()
        X = self.select_and_encode(df)

        # Save meta
        meta_cols = ["user", "day"]
        optional_meta_cols = [
            "department",
            "files_accessed",
            "usb_count",
            "emails_external",
            "after_hours_logins",
            "sensitive_files",
            "email_attachments",
            "session_duration_total",
            "unique_pcs",
        ]
        meta_cols.extend([col for col in optional_meta_cols if col in df.columns])
        meta = df[meta_cols].copy()

        # Train set: use all non-weekend rows as "normal" (we don't need labels for IsolationForest)
        X_scaled = self.fit_transform(X)

        # Save arrays
        np.save(os.path.join(self.model_dir, "X_all.npy"), X_scaled)
        meta.to_parquet(os.path.join(self.model_dir, "X_meta.parquet"), index=False)

        # For training, optionally exclude obvious weekend outliers
        train_mask = df["is_weekend"] == 0 if "is_weekend" in df.columns else pd.Series([True] * len(df))
        X_train = X_scaled[train_mask.values]
        np.save(os.path.join(self.model_dir, "X_train.npy"), X_train)

        logger.info(f"X_all: {X_scaled.shape}, X_train: {X_train.shape}")
        logger.info("Feature engineering complete.")
        return X_scaled, X_train, meta


if __name__ == "__main__":
    fe = FeatureEngineer()
    fe.run()
