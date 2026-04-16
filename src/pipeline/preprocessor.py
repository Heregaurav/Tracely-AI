"""
Data Preprocessing Pipeline
============================
Loads all 5 raw CERT CSV files, cleans them, normalizes timestamps,
and merges into a unified per-user-per-day behavioral matrix.

Output: data/processed/daily_behavior.parquet
"""

import pandas as pd
import numpy as np
import os
import yaml
import logging
from datetime import datetime, time
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


class CERTPreprocessor:
    """
    Full preprocessing pipeline for CERT Insider Threat Dataset.
    Handles both real CERT r4.2 files and synthetic generated files.
    """

    def __init__(self, config_path="config.yaml"):
        self.cfg = load_config(config_path)
        self.raw_dir = self.cfg["paths"]["raw_data"]
        self.proc_dir = self.cfg["paths"]["processed_data"]
        os.makedirs(self.proc_dir, exist_ok=True)
        self.biz_start = self.cfg["data"]["business_hours"]["start"]
        self.biz_end = self.cfg["data"]["business_hours"]["end"]

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------
    def _load_csv(self, name, required_cols=None):
        path = os.path.join(self.raw_dir, self.cfg["data"]["files"][name])
        if not os.path.exists(path):
            logger.warning(f"File not found: {path}")
            return pd.DataFrame()
        df = pd.read_csv(path, low_memory=False)
        logger.info(f"Loaded {name}: {len(df):,} rows, {list(df.columns)}")
        # Standardize column names
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        return df

    def _parse_dates(self, df, col="date"):
        """Parse multiple date formats robustly."""
        if col not in df.columns:
            return df
        df = df.copy()
        df[col] = pd.to_datetime(df[col], errors="coerce")
        n_bad = df[col].isna().sum()
        if n_bad > 0:
            logger.warning(f"  {n_bad} unparseable dates dropped")
            df = df.dropna(subset=[col])
        return df

    # ------------------------------------------------------------------
    # Per-source cleaning
    # ------------------------------------------------------------------
    def clean_logon(self, df):
        """Clean logon events. Extract session duration by pairing logon/logoff."""
        if df.empty:
            return df
        df = self._parse_dates(df)
        df = df.dropna(subset=["user", "date"])
        df["hour"] = df["date"].dt.hour
        df["day"] = df["date"].dt.date
        df["is_after_hours"] = ~df["hour"].between(self.biz_start, self.biz_end - 1)

        # Pair logon ↔ logoff to compute session duration
        sessions = []
        for (user, day), grp in df.groupby(["user", "day"]):
            logons = grp[grp["activity"].str.lower() == "logon"].sort_values("date")
            logoffs = grp[grp["activity"].str.lower() == "logoff"].sort_values("date")
            # Simplistic pairing: zip first N
            for lo, lf in zip(logons["date"], logoffs["date"]):
                dur = max(0, (lf - lo).total_seconds() / 60)
                if dur < 600:  # cap at 10 hours
                    sessions.append({"user": user, "day": day, "session_minutes": dur})
        session_df = pd.DataFrame(sessions) if sessions else pd.DataFrame(
            columns=["user", "day", "session_minutes"]
        )
        return df, session_df

    def clean_file(self, df):
        if df.empty:
            return df
        df = self._parse_dates(df)
        df = df.dropna(subset=["user", "date"])
        df["hour"] = df["date"].dt.hour
        df["day"] = df["date"].dt.date
        df["is_after_hours"] = ~df["hour"].between(self.biz_start, self.biz_end - 1)
        df["is_sensitive"] = df.get("filename", pd.Series(dtype=str)).str.contains(
            "confidential|secret|private|salary|credential|strategy", case=False, na=False
        )
        return df

    def clean_device(self, df):
        if df.empty:
            return df
        df = self._parse_dates(df)
        df = df.dropna(subset=["user", "date"])
        df["hour"] = df["date"].dt.hour
        df["day"] = df["date"].dt.date
        df["is_after_hours"] = ~df["hour"].between(self.biz_start, self.biz_end - 1)
        return df

    def clean_email(self, df):
        if df.empty:
            return df
        df = self._parse_dates(df)
        df = df.dropna(subset=["user", "date"])
        df["hour"] = df["date"].dt.hour
        df["day"] = df["date"].dt.date
        # Detect external emails
        internal_domain = "dtaa.com"
        to_col = "to" if "to" in df.columns else None
        if to_col:
            df["is_external"] = ~df[to_col].str.contains(internal_domain, na=False)
        else:
            df["is_external"] = False
        if "attachments" not in df.columns:
            df["attachments"] = 0
        df["attachments"] = pd.to_numeric(df["attachments"], errors="coerce").fillna(0).astype(int)
        return df

    # ------------------------------------------------------------------
    # Feature aggregation (per user per day)
    # ------------------------------------------------------------------
    def aggregate_features(self, logon_df, session_df, file_df, device_df, email_df, ldap_df):
        """
        Aggregate all cleaned dataframes into a per-user-per-day feature matrix.
        Returns a DataFrame with one row per (user, day).
        """
        logger.info("Aggregating features per user per day...")

        # --- Logon features ---
        if not logon_df.empty:
            logon_agg = logon_df.groupby(["user", "day"]).agg(
                login_count=("activity", "count"),
                login_hour_mean=("hour", "mean"),
                login_hour_std=("hour", "std"),
                after_hours_logins=("is_after_hours", "sum"),
                unique_pcs=("pc", "nunique"),
            ).reset_index()
            logon_agg["login_hour_std"] = logon_agg["login_hour_std"].fillna(0)
        else:
            logon_agg = pd.DataFrame()

        # --- Session features ---
        if not session_df.empty:
            sess_agg = session_df.groupby(["user", "day"]).agg(
                session_duration_total=("session_minutes", "sum"),
                session_count=("session_minutes", "count"),
            ).reset_index()
        else:
            sess_agg = pd.DataFrame()

        # --- File features ---
        if not file_df.empty:
            file_agg = file_df.groupby(["user", "day"]).agg(
                files_accessed=("activity", "count"),
                files_after_hours=("is_after_hours", "sum"),
                sensitive_files=("is_sensitive", "sum"),
            ).reset_index()
        else:
            file_agg = pd.DataFrame()

        # --- Device features ---
        if not device_df.empty:
            device_agg = device_df.groupby(["user", "day"]).agg(
                usb_count=("activity", "count"),
                usb_after_hours=("is_after_hours", "sum"),
            ).reset_index()
        else:
            device_agg = pd.DataFrame()

        # --- Email features ---
        if not email_df.empty:
            email_agg = email_df.groupby(["user", "day"]).agg(
                emails_sent=("activity", "count"),
                emails_external=("is_external", "sum"),
                email_attachments=("attachments", "sum"),
            ).reset_index()
        else:
            email_agg = pd.DataFrame()

        # --- Merge all ---
        # Start with logon as the spine
        if not logon_agg.empty:
            merged = logon_agg
        else:
            # Build from any available frame
            avail = [f for f in [file_agg, device_agg, email_agg] if not f.empty]
            if not avail:
                raise ValueError("No data available to aggregate!")
            merged = avail[0][["user", "day"]].drop_duplicates()

        for df, key in [
            (sess_agg, "session"),
            (file_agg, "file"),
            (device_agg, "device"),
            (email_agg, "email"),
        ]:
            if not df.empty:
                merged = merged.merge(df, on=["user", "day"], how="left")

        # Fill NaN for missing activity days
        fill_cols = [c for c in merged.columns if c not in ("user", "day")]
        merged[fill_cols] = merged[fill_cols].fillna(0)

        # --- LDAP join ---
        if not ldap_df.empty:
            ldap_mini = ldap_df[["user_id", "department", "role"]].rename(columns={"user_id": "user"})
            merged = merged.merge(ldap_mini, on="user", how="left")

        # --- Derived features ---
        merged["after_hours_ratio"] = np.where(
            merged["login_count"] > 0,
            merged["after_hours_logins"] / merged["login_count"],
            0,
        )
        merged["files_per_session"] = np.where(
            merged.get("session_count", pd.Series(1, index=merged.index)) > 0,
            merged.get("files_accessed", pd.Series(0, index=merged.index)) /
            merged.get("session_count", pd.Series(1, index=merged.index)).replace(0, 1),
            0,
        )

        # Day of week
        merged["day"] = pd.to_datetime(merged["day"])
        merged["day_of_week"] = merged["day"].dt.dayofweek  # 0=Mon
        merged["is_weekend"] = merged["day_of_week"].isin([5, 6]).astype(int)

        logger.info(f"Feature matrix shape: {merged.shape}")
        return merged

    # ------------------------------------------------------------------
    # Rolling baseline & deviation features
    # ------------------------------------------------------------------
    def add_rolling_features(self, df, window=7):
        """
        Add rolling 7-day baselines and deviation scores per user.
        These are the most powerful features for anomaly detection.
        """
        logger.info(f"Computing {window}-day rolling baselines...")
        df = df.sort_values(["user", "day"]).copy()

        numeric_cols = [
            "files_accessed", "usb_count", "emails_external",
            "after_hours_ratio", "sensitive_files", "email_attachments",
            "session_duration_total",
        ]
        numeric_cols = [c for c in numeric_cols if c in df.columns]

        for col in numeric_cols:
            roll = df.groupby("user")[col].transform(
                lambda x: x.shift(1).rolling(window, min_periods=1).mean()
            )
            std_roll = df.groupby("user")[col].transform(
                lambda x: x.shift(1).rolling(window, min_periods=1).std()
            )
            std_roll = std_roll.fillna(1).replace(0, 1)
            df[f"{col}_deviation"] = (df[col] - roll) / std_roll

        df = df.fillna(0)
        return df

    # ------------------------------------------------------------------
    # Full pipeline run
    # ------------------------------------------------------------------
    def run(self):
        logger.info("=" * 60)
        logger.info("  CERT PREPROCESSING PIPELINE STARTING")
        logger.info("=" * 60)

        # Load raw data
        ldap_raw = self._load_csv("ldap")
        logon_raw = self._load_csv("logon")
        file_raw = self._load_csv("file")
        device_raw = self._load_csv("device")
        email_raw = self._load_csv("email")

        # Clean each source
        logon_clean, session_df = (self.clean_logon(logon_raw)
                                    if not logon_raw.empty
                                    else (pd.DataFrame(), pd.DataFrame()))
        file_clean = self.clean_file(file_raw)
        device_clean = self.clean_device(device_raw)
        email_clean = self.clean_email(email_raw)

        # Save cleaned files
        for name, df in [
            ("logon_clean", logon_clean),
            ("file_clean", file_clean),
            ("device_clean", device_clean),
            ("email_clean", email_clean),
        ]:
            if not df.empty:
                df.to_parquet(os.path.join(self.proc_dir, f"{name}.parquet"), index=False)

        # Aggregate features
        features_df = self.aggregate_features(
            logon_clean, session_df, file_clean, device_clean, email_clean, ldap_raw
        )

        # Add rolling baselines
        features_df = self.add_rolling_features(features_df)

        # Save feature matrix
        out_path = os.path.join(self.proc_dir, "daily_behavior.parquet")
        features_df.to_parquet(out_path, index=False)
        logger.info(f"Feature matrix saved → {out_path}")
        logger.info(f"Shape: {features_df.shape[0]:,} rows × {features_df.shape[1]} features")
        logger.info(f"Users: {features_df['user'].nunique():,}")
        logger.info(f"Date range: {features_df['day'].min()} → {features_df['day'].max()}")

        return features_df


if __name__ == "__main__":
    preprocessor = CERTPreprocessor()
    df = preprocessor.run()
    print(df.describe())
