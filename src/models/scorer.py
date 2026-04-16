"""
Anomaly Scoring Engine
========================
Combines Isolation Forest + Autoencoder scores using weighted ensemble.
Produces per-user risk scores, tier classifications, and alert records.

Risk tiers:
  NORMAL   < 40  — baseline behavior
  LOW      40-70 — slight deviation, watch
  MEDIUM   70-85 — significant anomaly, investigate
  HIGH     85-95 — strong anomaly, escalate
  CRITICAL > 95  — immediate action required
"""

import pandas as pd
import numpy as np
import os
import yaml
import json
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


TIER_COLORS = {
    "NORMAL":   "#4ade80",
    "LOW":      "#facc15",
    "MEDIUM":   "#fb923c",
    "HIGH":     "#f87171",
    "CRITICAL": "#dc2626",
}

TIER_ICONS = {
    "NORMAL":   "shield",
    "LOW":      "eye",
    "MEDIUM":   "alert-triangle",
    "HIGH":     "alert-octagon",
    "CRITICAL": "skull",
}


class ScoringEngine:
    """
    Combines model scores, computes ensemble risk,
    classifies risk tiers, and generates alerts.
    """

    def __init__(self, config_path="config.yaml"):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)
        self.score_cfg = self.cfg["scoring"]
        self.thresholds = self.score_cfg["thresholds"]
        self.weights = self.score_cfg["weights"]
        self.model_dir = self.cfg["paths"]["models"]
        self.proc_dir = self.cfg["paths"]["processed_data"]
        self.reports_dir = self.cfg["paths"]["reports"]
        os.makedirs(self.reports_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Score combination
    # ------------------------------------------------------------------
    def ensemble_score(self, if_scores, ae_scores):
        """Weighted combination of Isolation Forest and Autoencoder scores."""
        w_if = self.weights["isolation_forest"]
        w_ae = self.weights["autoencoder"]
        combined = (w_if * if_scores + w_ae * ae_scores) / (w_if + w_ae)
        return np.clip(combined, 0, 100)

    def classify_tier(self, score):
        """Classify a score into a risk tier string."""
        if score >= self.thresholds["critical"]:
            return "CRITICAL"
        elif score >= self.thresholds["high"]:
            return "HIGH"
        elif score >= self.thresholds["medium"]:
            return "MEDIUM"
        elif score >= self.thresholds["low"]:
            return "LOW"
        else:
            return "NORMAL"

    # ------------------------------------------------------------------
    # Per-day scoring
    # ------------------------------------------------------------------
    def score_all(self, meta_df, if_scores, ae_scores):
        """
        Attach scores to metadata, compute tiers, return scored DataFrame.
        """
        df = meta_df.copy()
        df["if_score"] = np.round(if_scores, 2)
        df["ae_score"] = np.round(ae_scores, 2)
        df["risk_score"] = np.round(self.ensemble_score(if_scores, ae_scores), 2)
        df["risk_tier"] = df["risk_score"].apply(self.classify_tier)
        df["scored_at"] = datetime.utcnow().isoformat()
        return df

    # ------------------------------------------------------------------
    # User-level aggregation
    # ------------------------------------------------------------------
    def aggregate_user_risk(self, scored_df, window_days=30):
        """
        Compute rolling aggregate risk per user.
        Uses the most recent `window_days` days.
        """
        scored_df = scored_df.copy()
        scored_df["day"] = pd.to_datetime(scored_df["day"])
        cutoff = scored_df["day"].max() - timedelta(days=window_days)
        recent = scored_df[scored_df["day"] >= cutoff]

        agg = recent.groupby("user").agg(
            max_risk_score=("risk_score", "max"),
            avg_risk_score=("risk_score", "mean"),
            high_risk_days=("risk_tier", lambda x: (x.isin(["HIGH", "CRITICAL"])).sum()),
            medium_risk_days=("risk_tier", lambda x: (x == "MEDIUM").sum()),
            latest_score=("risk_score", "last"),
            latest_day=("day", "max"),
            total_days_active=("day", "nunique"),
        ).reset_index()

        # Department
        if "department" in scored_df.columns:
            dept = scored_df.groupby("user")["department"].first().reset_index()
            agg = agg.merge(dept, on="user", how="left")

        # Overall risk tier based on max score
        agg["risk_tier"] = agg["max_risk_score"].apply(self.classify_tier)

        # Trend: compare last 7 days to previous 7 days
        agg["trend"] = agg.apply(
            lambda row: self._compute_trend(scored_df, row["user"]), axis=1
        )
        return agg.sort_values("max_risk_score", ascending=False)

    def _compute_trend(self, scored_df, user, window=7):
        """Returns 'up', 'down', or 'stable' based on recent score trend."""
        user_df = scored_df[scored_df["user"] == user].sort_values("day")
        if len(user_df) < 4:
            return "stable"
        recent_7 = user_df.tail(7)["risk_score"].mean()
        prev_7 = user_df.iloc[-14:-7]["risk_score"].mean() if len(user_df) >= 14 else user_df.head(7)["risk_score"].mean()
        delta = recent_7 - prev_7
        if delta > 5:
            return "up"
        elif delta < -5:
            return "down"
        return "stable"

    # ------------------------------------------------------------------
    # Alert generation
    # ------------------------------------------------------------------
    def generate_alerts(self, scored_df, user_risk_df):
        """
        Generate alert records for anomalous days.
        Returns DataFrame of alerts sorted by severity.
        """
        alerts = []

        # Alert on every HIGH/CRITICAL day
        high_days = scored_df[scored_df["risk_tier"].isin(["HIGH", "CRITICAL"])].copy()
        for _, row in high_days.iterrows():
            alert = {
                "alert_id": f"ALT-{len(alerts)+1:05d}",
                "timestamp": str(row.get("day", "")) + "T00:00:00Z",
                "user_id": row["user"],
                "department": row.get("department", "Unknown"),
                "risk_score": row["risk_score"],
                "risk_tier": row["risk_tier"],
                "if_score": row.get("if_score", 0),
                "ae_score": row.get("ae_score", 0),
                "alert_type": "DAILY_ANOMALY",
                "status": "OPEN",
                "message": self._alert_message(row),
                "color": TIER_COLORS.get(row["risk_tier"], "#666"),
            }
            alerts.append(alert)

        # Alert on users with rapidly rising scores
        rising_users = user_risk_df[user_risk_df["trend"] == "up"]
        for _, row in rising_users.iterrows():
            if row["risk_tier"] in ["MEDIUM", "HIGH", "CRITICAL"]:
                alerts.append({
                    "alert_id": f"ALT-{len(alerts)+1:05d}",
                    "timestamp": str(row.get("latest_day", "")) + "T00:00:00Z",
                    "user_id": row["user"],
                    "department": row.get("department", "Unknown"),
                    "risk_score": row["avg_risk_score"],
                    "risk_tier": row["risk_tier"],
                    "if_score": None,
                    "ae_score": None,
                    "alert_type": "RISING_TREND",
                    "status": "OPEN",
                    "message": f"User {row['user']} shows escalating risk trend over past 14 days.",
                    "color": TIER_COLORS.get(row["risk_tier"], "#666"),
                })

        alerts_df = pd.DataFrame(alerts)
        if not alerts_df.empty:
            alerts_df = alerts_df.sort_values("risk_score", ascending=False).reset_index(drop=True)

        logger.info(f"Generated {len(alerts_df)} alerts "
                    f"({(alerts_df['risk_tier'] == 'CRITICAL').sum()} CRITICAL, "
                    f"{(alerts_df['risk_tier'] == 'HIGH').sum()} HIGH)")
        return alerts_df

    def _alert_message(self, row):
        score = row["risk_score"]
        user = row["user"]
        if score >= 95:
            return (f"CRITICAL: {user} exhibits extreme behavioral anomaly. "
                    "Immediate investigation required.")
        elif score >= 85:
            return (f"HIGH RISK: {user} shows significant deviation from baseline. "
                    "Escalate to security team.")
        elif score >= 70:
            return (f"MEDIUM: {user} has notable behavioral changes. "
                    "Schedule review.")
        else:
            return f"LOW: {user} shows minor behavioral deviation."

    # ------------------------------------------------------------------
    # Save results
    # ------------------------------------------------------------------
    def save_results(self, scored_df, user_risk_df, alerts_df):
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        scored_path = os.path.join(self.proc_dir, "scored_behaviors.parquet")
        users_path  = os.path.join(self.proc_dir, "user_risk_scores.parquet")
        alerts_path = os.path.join(self.proc_dir, "alerts.parquet")
        json_path   = os.path.join(self.reports_dir, f"threat_report_{ts}.json")

        scored_df.to_parquet(scored_path, index=False)
        user_risk_df.to_parquet(users_path, index=False)
        alerts_df.to_parquet(alerts_path, index=False)

        # JSON summary for API
        summary = {
            "generated_at": ts,
            "total_users": int(user_risk_df["user"].nunique()),
            "total_alerts": len(alerts_df),
            "critical_alerts": int((alerts_df.get("risk_tier", pd.Series()) == "CRITICAL").sum()),
            "high_alerts": int((alerts_df.get("risk_tier", pd.Series()) == "HIGH").sum()),
            "tier_distribution": user_risk_df["risk_tier"].value_counts().to_dict(),
        }
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Results saved:")
        logger.info(f"  Scored behaviors → {scored_path}")
        logger.info(f"  User risk scores → {users_path}")
        logger.info(f"  Alerts           → {alerts_path}")
        logger.info(f"  JSON report      → {json_path}")
        return summary
