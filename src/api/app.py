"""
Flask REST API
===============
Serves the Insider Threat Detection Dashboard with real-time data.

Endpoints:
  GET  /api/stats              — system summary statistics
  GET  /api/threats            — paginated list of alerts
  GET  /api/users              — all users with risk scores
  GET  /api/users/<user_id>    — detailed user profile
  GET  /api/timeline           — daily risk score history
  GET  /api/heatmap            — risk heatmap data (dept × week)
  GET  /api/user-events/<uid>  — raw events for a user
  POST /api/retrain            — trigger model retraining
  GET  /health                 — health check
"""

import os
import sys
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from functools import wraps

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="../../dashboard/static",
            template_folder="../../dashboard/templates")
CORS(app)

# ---------------------------------------------------------------------------
# Data loader — loads parquet files into memory once at startup
# ---------------------------------------------------------------------------
class DataStore:
    def __init__(self):
        self.scored_df = None
        self.user_risk_df = None
        self.alerts_df = None
        self.ldap_df = None
        self.logon_df = None
        self.file_df = None
        self.device_df = None
        self.email_df = None
        self.loaded = False
        self.load()

    def load(self):
        """Load all processed data files."""
        try:
            proc = "data/processed"
            raw = "data/raw"

            def safe_parquet(path):
                return pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()

            def safe_csv(path):
                return pd.read_csv(path, low_memory=False) if os.path.exists(path) else pd.DataFrame()

            self.scored_df   = safe_parquet(f"{proc}/scored_behaviors.parquet")
            self.user_risk_df = safe_parquet(f"{proc}/user_risk_scores.parquet")
            self.alerts_df   = safe_parquet(f"{proc}/alerts.parquet")
            self.ldap_df     = safe_csv(f"{raw}/LDAP.csv")

            # Convert dates
            if not self.scored_df.empty and "day" in self.scored_df.columns:
                self.scored_df["day"] = pd.to_datetime(self.scored_df["day"])
            if not self.user_risk_df.empty and "latest_day" in self.user_risk_df.columns:
                self.user_risk_df["latest_day"] = pd.to_datetime(self.user_risk_df["latest_day"])

            n_users  = self.user_risk_df["user"].nunique() if not self.user_risk_df.empty else 0
            n_alerts = len(self.alerts_df) if not self.alerts_df.empty else 0
            logger.info(f"DataStore loaded: {n_users} users, {n_alerts} alerts")
            self.loaded = True

        except Exception as e:
            logger.error(f"DataStore load error: {e}")
            self.loaded = False

    def reload(self):
        self.load()


store = DataStore()


# ---------------------------------------------------------------------------
# Helper: serialize DataFrames to JSON-safe dicts
# ---------------------------------------------------------------------------
def df_to_records(df, limit=None, offset=0):
    if df is None or df.empty:
        return []
    sub = df.iloc[offset:offset + limit] if limit else df
    return json.loads(sub.to_json(orient="records", date_format="iso", default_handler=str))


def error_response(msg, code=500):
    return jsonify({"error": msg, "status": "error"}), code


ALERT_STATUS_VALUES = {"OPEN", "IN_PROGRESS", "RESOLVED"}


def persist_alerts():
    alerts_path = "data/processed/alerts.parquet"
    if store.alerts_df is None:
        raise ValueError("Alerts data is not loaded.")
    store.alerts_df.to_parquet(alerts_path, index=False)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "data_loaded": store.loaded,
        "timestamp": datetime.utcnow().isoformat(),
    })


@app.route("/")
def index():
    return send_from_directory("../../dashboard", "index.html")


# ------------------------------------------------------------------
# GET /api/stats
# ------------------------------------------------------------------
@app.route("/api/stats")
def stats():
    try:
        ur = store.user_risk_df
        al = store.alerts_df
        sc = store.scored_df

        if ur.empty:
            return error_response("No scored data available. Run training first.", 404)

        tier_dist = ur["risk_tier"].value_counts().to_dict() if "risk_tier" in ur.columns else {}
        total_users = int(ur["user"].nunique())
        critical_count = int((ur.get("risk_tier", pd.Series()) == "CRITICAL").sum())
        high_count = int((ur.get("risk_tier", pd.Series()) == "HIGH").sum())
        open_statuses = {"OPEN", "IN_PROGRESS"}
        open_alerts = int(al.get("status", pd.Series()).isin(open_statuses).sum()) if not al.empty else 0

        # Score trend: avg risk for last 7 days vs previous 7
        trend_pct = 0.0
        if not sc.empty and "day" in sc.columns:
            sc_copy = sc.copy()
            sc_copy["day"] = pd.to_datetime(sc_copy["day"])
            latest = sc_copy["day"].max()
            last7 = sc_copy[sc_copy["day"] >= latest - timedelta(days=7)]["risk_score"].mean()
            prev7 = sc_copy[(sc_copy["day"] >= latest - timedelta(days=14)) &
                            (sc_copy["day"] < latest - timedelta(days=7))]["risk_score"].mean()
            if prev7 and prev7 > 0:
                trend_pct = round(((last7 - prev7) / prev7) * 100, 1)

        return jsonify({
            "total_users": total_users,
            "critical_users": critical_count,
            "high_risk_users": high_count,
            "open_alerts": open_alerts,
            "tier_distribution": tier_dist,
            "risk_trend_pct": trend_pct,
            "avg_risk_score": round(float(ur.get("avg_risk_score", pd.Series([0])).mean()), 1),
            "last_updated": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        logger.error(f"/api/stats error: {e}")
        return error_response(str(e))


# ------------------------------------------------------------------
# GET /api/threats  ?tier=HIGH&page=1&limit=50
# ------------------------------------------------------------------
@app.route("/api/threats")
def threats():
    try:
        al = store.alerts_df.copy() if not store.alerts_df.empty else pd.DataFrame()
        if al.empty:
            return jsonify({"alerts": [], "total": 0})

        tier_filter = request.args.get("tier")
        if tier_filter:
            al = al[al["risk_tier"] == tier_filter.upper()]

        page  = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 50))
        offset = (page - 1) * limit

        records = df_to_records(al, limit=limit, offset=offset)
        return jsonify({"alerts": records, "total": len(al), "page": page, "limit": limit})
    except Exception as e:
        return error_response(str(e))


@app.route("/api/threats/<alert_id>/status", methods=["POST"])
def update_threat_status(alert_id):
    try:
        if store.alerts_df is None or store.alerts_df.empty:
            return error_response("No alerts available.", 404)

        payload = request.get_json(silent=True) or {}
        status = str(payload.get("status", "")).upper().strip()
        if status not in ALERT_STATUS_VALUES:
            return error_response(f"Invalid status '{status}'.", 400)

        mask = store.alerts_df["alert_id"] == alert_id
        if not mask.any():
            return error_response(f"Alert {alert_id} not found.", 404)

        store.alerts_df.loc[mask, "status"] = status
        persist_alerts()

        updated_alert = store.alerts_df.loc[mask].iloc[0]
        return jsonify({
            "status": "ok",
            "message": f"Alert {alert_id} updated to {status}.",
            "alert": json.loads(updated_alert.to_json(default_handler=str)),
        })
    except Exception as e:
        logger.error(f"/api/threats/{alert_id}/status error: {e}")
        return error_response(str(e))


# ------------------------------------------------------------------
# GET /api/users  ?sort=risk_score&order=desc&dept=Finance
# ------------------------------------------------------------------
@app.route("/api/users")
def users():
    try:
        ur = store.user_risk_df.copy() if not store.user_risk_df.empty else pd.DataFrame()
        if ur.empty:
            return jsonify({"users": [], "total": 0})

        dept_filter = request.args.get("dept")
        if dept_filter:
            ur = ur[ur.get("department", pd.Series()) == dept_filter]

        tier_filter = request.args.get("tier")
        if tier_filter:
            ur = ur[ur["risk_tier"] == tier_filter.upper()]

        sort_col = request.args.get("sort", "max_risk_score")
        order = request.args.get("order", "desc") == "desc"
        if sort_col in ur.columns:
            ur = ur.sort_values(sort_col, ascending=not order)

        page  = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 100))
        offset = (page - 1) * limit

        # Add LDAP name if available
        if not store.ldap_df.empty and "user_id" in store.ldap_df.columns:
            name_map = dict(zip(store.ldap_df["user_id"], store.ldap_df.get("name", [""])))
            role_map = dict(zip(store.ldap_df["user_id"], store.ldap_df.get("role", [""])))
            ur["name"] = ur["user"].map(name_map).fillna("Unknown")
            ur["role"] = ur["user"].map(role_map).fillna("")

        records = df_to_records(ur, limit=limit, offset=offset)
        return jsonify({"users": records, "total": len(ur)})
    except Exception as e:
        return error_response(str(e))


# ------------------------------------------------------------------
# GET /api/users/<user_id>
# ------------------------------------------------------------------
@app.route("/api/users/<user_id>")
def user_detail(user_id):
    try:
        ur = store.user_risk_df
        if ur.empty:
            return error_response("No data", 404)

        user_row = ur[ur["user"] == user_id]
        if user_row.empty:
            return error_response(f"User {user_id} not found", 404)

        user_data = json.loads(user_row.iloc[0].to_json(default_handler=str))

        # LDAP info
        if not store.ldap_df.empty:
            ldap_row = store.ldap_df[store.ldap_df.get("user_id", pd.Series()) == user_id]
            if not ldap_row.empty:
                user_data["ldap"] = json.loads(ldap_row.iloc[0].to_json(default_handler=str))

        # Daily history
        sc = store.scored_df
        if not sc.empty:
            user_history = sc[sc["user"] == user_id].sort_values("day")
            user_data["daily_scores"] = df_to_records(user_history)

        # Alerts for this user
        al = store.alerts_df
        if not al.empty:
            user_alerts = al[al["user_id"] == user_id].sort_values("risk_score", ascending=False)
            user_data["alerts"] = df_to_records(user_alerts, limit=20)

        return jsonify(user_data)
    except Exception as e:
        return error_response(str(e))


# ------------------------------------------------------------------
# GET /api/timeline  ?days=30&user_id=CER0001
# ------------------------------------------------------------------
@app.route("/api/timeline")
def timeline():
    try:
        sc = store.scored_df.copy() if not store.scored_df.empty else pd.DataFrame()
        if sc.empty:
            return jsonify({"timeline": []})

        sc["day"] = pd.to_datetime(sc["day"])
        days = int(request.args.get("days", 30))
        cutoff = sc["day"].max() - timedelta(days=days)
        sc = sc[sc["day"] >= cutoff]

        user_id = request.args.get("user_id")
        if user_id:
            sc = sc[sc["user"] == user_id]
            daily = sc[["day", "risk_score", "if_score", "ae_score", "risk_tier"]].copy()
        else:
            # Aggregate all users: avg and max per day
            daily = sc.groupby("day").agg(
                risk_score_avg=("risk_score", "mean"),
                risk_score_max=("risk_score", "max"),
                n_anomalies=("risk_tier", lambda x: (x.isin(["HIGH", "CRITICAL"])).sum()),
            ).reset_index()

        daily["day"] = daily["day"].dt.strftime("%Y-%m-%d")
        return jsonify({"timeline": df_to_records(daily)})
    except Exception as e:
        return error_response(str(e))


# ------------------------------------------------------------------
# GET /api/heatmap  — dept × day-of-week risk heatmap
# ------------------------------------------------------------------
@app.route("/api/heatmap")
def heatmap():
    try:
        sc = store.scored_df.copy() if not store.scored_df.empty else pd.DataFrame()
        if sc.empty or "department" not in sc.columns:
            return jsonify({"heatmap": []})

        sc["day"] = pd.to_datetime(sc["day"])
        sc["dow"] = sc["day"].dt.day_name()

        heat = sc.groupby(["department", "dow"])["risk_score"].mean().reset_index()
        heat.columns = ["department", "dow", "avg_risk"]
        heat["avg_risk"] = heat["avg_risk"].round(1)
        return jsonify({"heatmap": df_to_records(heat)})
    except Exception as e:
        return error_response(str(e))


# ------------------------------------------------------------------
# GET /api/departments  — department-level stats
# ------------------------------------------------------------------
@app.route("/api/departments")
def departments():
    try:
        ur = store.user_risk_df.copy()
        if ur.empty or "department" not in ur.columns:
            return jsonify({"departments": []})

        dept_stats = ur.groupby("department").agg(
            user_count=("user", "count"),
            avg_risk=("avg_risk_score", "mean"),
            max_risk=("max_risk_score", "max"),
            critical_count=("risk_tier", lambda x: (x == "CRITICAL").sum()),
            high_count=("risk_tier", lambda x: (x == "HIGH").sum()),
        ).reset_index()
        dept_stats = dept_stats.round(2)
        return jsonify({"departments": df_to_records(dept_stats)})
    except Exception as e:
        return error_response(str(e))


# ------------------------------------------------------------------
# POST /api/retrain
# ------------------------------------------------------------------
@app.route("/api/retrain", methods=["POST"])
def retrain():
    """Trigger retraining in background thread."""
    import threading

    def _retrain():
        try:
            from scripts.train import run_training
            run_training()
            store.reload()
            logger.info("Retraining complete. DataStore reloaded.")
        except Exception as e:
            logger.error(f"Retraining failed: {e}")

    t = threading.Thread(target=_retrain, daemon=True)
    t.start()
    return jsonify({"status": "retraining_started", "message": "Model retraining initiated."})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import yaml
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    api_cfg = cfg.get("api", {})
    app.run(
        host=api_cfg.get("host", "0.0.0.0"),
        port=api_cfg.get("port", 5000),
        debug=api_cfg.get("debug", True),
    )
