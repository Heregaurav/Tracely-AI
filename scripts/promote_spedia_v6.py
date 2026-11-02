"""Package frozen V6 Maximum without fitting; stage and activate only explicitly."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from src.data.integrity import atomic_json, sha256_file, utcnow
from src.data.spedia import load_spedia, prepare_events
from src.data.spedia_behavioral_v6 import NAMES, features_for_windows
from src.db.models import (Alert, AuditLog, DailyBehavior, DailyScore, Dataset,
                           ModelVersion, Principal, Relationship, StoredAsset)
from src.db.session import database
from src.models.behavioral import metrics
from src.models.v6_maximum import V6MaximumDetector, serving_contract

VERSION = "spedia-v6-maximum-20261102"
CANDIDATE = "behavior_55_if_ae_max"
DEFAULT_OUTPUT = Path("data/artifacts") / VERSION
EXPERIMENT = Path("data/spedia/origin-audit-v6-20261101/experiment")
BASE = Path("data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223")


def build(output=DEFAULT_OUTPUT):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Choose a new immutable publication directory")
    original = json.loads((BASE / "metrics.json").read_text())
    research = json.loads((EXPERIMENT / "experimental_metrics.json").read_text())
    candidate = research["candidates"][CANDIDATE]
    selected = candidate["budgets"]["50.0"]
    protected = [BASE / name for name in ("model.joblib", "scores.parquet", "metrics.json")]
    components = []
    for name in candidate["members"]:
        item = research["candidates"][name]
        path = EXPERIMENT / item["artifact"]
        if sha256_file(path) != item["artifact_sha256"]:
            raise ValueError("Frozen V6 component checksum mismatch")
        protected.append(path)
        components.append(joblib.load(path))  # Trusted, digest-verified offline checkpoints.
    before = {str(path): sha256_file(path) for path in protected}
    forest, neural = components
    if forest.names != NAMES or neural.names != NAMES or (forest.kind, neural.kind) != ("if", "ae"):
        raise ValueError("Wrong frozen V6 components")
    model = V6MaximumDetector(list(NAMES), copy.deepcopy(forest.estimator), copy.deepcopy(forest.scaler),
                              forest.reference.copy(), copy.deepcopy(neural.estimator),
                              copy.deepcopy(neural.scaler), neural.reference.copy(), selected["threshold"])
    raw = load_spedia("logs_SPEDIA_annotated_en.csv")
    if sha256_file("logs_SPEDIA_annotated_en.csv") != original["dataset"]["provenance"]["sha256"]:
        raise ValueError("Original source changed")
    events, _ = prepare_events(raw)
    base = pd.read_parquet(BASE / "scores.parquet")
    frame = features_for_windows(events, base)
    index, tiers, signals = model.score(frame[NAMES])
    validation = frame.split.eq("validation").to_numpy()
    expected = pd.read_parquet(EXPERIMENT / (CANDIDATE + "_validation.parquet")).set_index("window_id")
    np.testing.assert_array_equal(index[validation], expected.loc[frame.loc[validation, "window_id"], "index"])
    measured = metrics(frame.loc[validation, "label"], index[validation], model.threshold)
    if measured["confusion_matrix"] != selected["confusion_matrix"]:
        raise ValueError("Published adapter differs from saved V6 validation result")
    # No new test-quality metric is calculated. Other rows are operational historical rescoring.
    for column in list(frame):
        if column.endswith("_score") or column in ("risk_tier", "model_version", "explanation"):
            frame = frame.drop(columns=column)
    frame["risk_score"], frame["risk_tier"], frame["model_version"] = index, tiers, VERSION
    for key, values in signals.items():
        frame[key] = values
    frame["explanation"] = [json.dumps({
        "kind": "V6 maximum of frozen IF and neural indices; not proof of intent",
        "window_start": row.window_start, "window_index": int(row.window_index), "window_unit": "hour",
        "event_count": float(row.event_count), "volume_deviation": float(row.volume_deviation),
        "prior_7d_observed_window_mean": float(row.prior_events_mean_7d),
        "new_hosts": float(row.new_hosts), "history_windows": float(row.prior_observed_windows_7d),
        "evidence_record_ids": list(row.record_ids)[:5],
        "component_indices": {key: float(values[i]) for key, values in signals.items()},
        "limitation": "Historical operational rescoring. Only reused validation metrics are reported; source confounding remains."
    }) for i, row in enumerate(frame.itertuples())]
    output.mkdir(parents=True)
    joblib.dump(model, output / "model.joblib")
    frame.to_parquet(output / "scores.parquet", index=False)
    frame[["window_id", "user", "window_start", "window_index", "record_ids", *NAMES]].to_parquet(output / "features.parquet", index=False)
    relationships = pd.read_parquet(original["dataset"]["relationships_path"])
    relationships.to_parquet(output / "relationships.parquet", index=False)
    assets = {"inference_context": str(output / "inference-context"),
              "replay_analysis": str(output / "replay-analysis"), "replay_realistic": str(output / "replay-realistic")}
    for mode, previous in [("analysis", "data/spedia/review-v3"), ("realistic", "data/spedia/replay-realistic-v1")]:
        previous = Path(previous)
        manifest = json.loads((previous / "replay_manifest.json").read_text())
        chosen = frame.set_index("window_id").loc[manifest["window_ids"]].reset_index()
        target = output / ("replay-" + mode); target.mkdir()
        chosen[["window_id", "user", "window_start", "window_index", "record_ids", *NAMES]].to_parquet(target / "replay_inputs.parquet", index=False)
        shutil.copy2(previous / "replay_events.parquet", target / "replay_events.parquet")
        truth = [{"window_id": row.window_id, "label": bool(row.label),
                  "example_outcome": ("TP" if row.label else "FP") if row.risk_score >= model.threshold else ("FN" if row.label else "TN")}
                 for row in chosen.itertuples()]
        atomic_json(target / "replay_ground_truth.json", {"windows": truth})
        manifest.update(model_version=VERSION, model_directory=str(output),
                        inputs_sha256=sha256_file(target / "replay_inputs.parquet"),
                        events_sha256=sha256_file(target / "replay_events.parquet"),
                        ground_truth_sha256=sha256_file(target / "replay_ground_truth.json"),
                        feature_source=str(output / "features.parquet"), feature_source_sha256=sha256_file(output / "features.parquet"),
                        selection=manifest["selection"] + " V6 historical operational rescoring; not a new independent evaluation.")
        atomic_json(target / "replay_manifest.json", manifest)
    context = output / "inference-context"; context.mkdir()
    previous = Path("data/inference/context-v1")
    shutil.copy2(previous / "events.parquet", context / "events.parquet")
    manifest = json.loads((previous / "context.json").read_text())
    manifest.update(features_sha256=sha256_file(output / "features.parquet"), predictor_feature_version=model.feature_version)
    atomic_json(context / "context.json", manifest)
    report = copy.deepcopy(original)
    report.update(version=VERSION, created_at=utcnow(), active_configuration=CANDIDATE,
                  evaluation_scope="Reused development validation; not an independent test or real-world accuracy estimate",
                  primary_evaluation="validation", display_name="SPEDIA V6 Maximum", weights={},
                  fusion="maximum of IF and neural normal-reference percentile indices",
                  models={"isolation_forest": "Frozen V6 Isolation Forest", "neural": "Frozen V6 autoencoder", "reconstruction": "neural autoencoder"},
                  parameters={"refitted": False, "normal_calibration_budget_per_1000": 50},
                  contract=serving_contract(), scaling="Signed log followed by train-only RobustScaler for each frozen component",
                  selection_policy="Owner requested V6 Maximum after reviewing reused validation; highest observed V6 F1, not independent model selection evidence",
                  validation_metrics={CANDIDATE: measured}, held_out_metrics={},
                  primary_metrics=measured, runtime_assets=assets,
                  artifact_sha256=sha256_file(output / "model.joblib"), scores_sha256=sha256_file(output / "scores.parquet"),
                  calibration={"component_scale": "Frozen normal-training calibration empirical midrank percentiles",
                               "reference": "110 chronological normal original-train calibration hours",
                               "high_threshold": model.threshold, "tier_thresholds": model.cutoffs,
                               "index_is_probability": False, "normal_budget": selected["calibration"],
                               "tier_policy": "HIGH is the saved normal-budget threshold; other bands are display heuristics, not independently validated security levels"},
                  limitations=["Reused validation: 332 hours, 77 positive and 255 normal; no independent V6 held-out metrics.",
                               "Source markers perfectly track event labels; numerical features remain source-predictive.",
                               "All historical hours are operationally rescored; these outputs do not constitute a new benchmark.",
                               "User badges summarize the highest hourly risk; hourly distributions count hours instead of users."],
                  historical_baseline={"version": original["version"], "held_out_metrics": original["held_out_metrics"].get(original["active_configuration"] )})
    report["dataset"].update(contract=report["contract"], feature_version=model.feature_version,
                             features_sha256=sha256_file(output / "features.parquet"),
                             relationships_path=str((output / "relationships.parquet").resolve()),
                             relationships_sha256=sha256_file(output / "relationships.parquet"))
    atomic_json(output / "metrics.json", report)
    restored = joblib.load(output / "model.joblib")
    np.testing.assert_array_equal(restored.score(frame[NAMES])[0], index)
    if before != {str(path): sha256_file(path) for path in protected}:
        raise ValueError("Original artifacts changed")
    atomic_json(output / "verification.json", {"original_artifacts_unchanged": before, "validation_exact_replay": True,
                "confusion_matrix": measured["confusion_matrix"], "historical_windows": len(frame),
                "hourly_tiers": frame.risk_tier.value_counts().to_dict(), "model_refitted": False})
    return report


def stage(factory, root=DEFAULT_OUTPUT):
    """Store additive immutable assets and records, leaving the active model untouched."""
    root = Path(root)
    report = json.loads((root / "metrics.json").read_text())
    for filename, key in [("model.joblib", "artifact_sha256"), ("scores.parquet", "scores_sha256"), ("relationships.parquet", None)]:
        expected = report[key] if key else report["dataset"]["relationships_sha256"]
        if sha256_file(root / filename) != expected:
            raise ValueError("Publication checksum mismatch")
    frame = pd.read_parquet(root / "scores.parquet")
    if report["version"] != VERSION or list(item["name"] for item in report["contract"]["features"]) != NAMES:
        raise ValueError("Unsupported publication contract")
    with factory.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:dataset))"), {"dataset": report["dataset"]["dataset_id"]})
        if db.get(ModelVersion, VERSION):
            raise ValueError("Version already staged; refusing to overwrite")
        if not db.get(Dataset, report["dataset"]["dataset_id"]):
            raise ValueError("Publish the original source-backed dataset first")
        db.add(ModelVersion(id=VERSION, dataset_id=report["dataset"]["dataset_id"], feature_version=report["contract"]["version"],
                            artifact_path=str(root), artifact_sha256=report["artifact_sha256"], report=report, active=False))
        db.flush()
        for path in sorted(root.rglob("*")):
            if not path.is_file(): continue
            key = path.as_posix()
            old = db.get(StoredAsset, key)
            digest = sha256_file(path)
            if old:
                if old.sha256 != digest: raise ValueError("Immutable asset conflict")
                continue
            content = path.read_bytes()
            db.add(StoredAsset(asset_key=key, sha256=digest, size_bytes=len(content), content=content,
                               media_type="application/octet-stream"))
        principal_rows = [{"dataset_id": report["dataset"]["dataset_id"], "user": user} for user in frame.user.unique()]
        db.execute(insert(Principal).values(principal_rows).on_conflict_do_nothing())
        behaviors, scores, alerts = [], [], []
        for row in frame.to_dict("records"):
            key = dict(dataset_id=row["dataset_id"], user=row["user"], relative_day=int(row["window_index"]), feature_version=report["contract"]["version"])
            score_id = hashlib.sha256(f"{row['dataset_id']}|{VERSION}|{row['user']}|{row['window_index']}".encode()).hexdigest()
            behaviors.append({**key, "values": {name: float(row[name]) for name in NAMES}})
            scores.append({**key, "id": score_id, "model_version": VERSION, "risk_score": float(row["risk_score"]),
                           "risk_tier": row["risk_tier"], "components": {name: float(row[name]) for name in ("if_score", "neural_score")},
                           "explanation": json.loads(row["explanation"])})
            if row["risk_tier"] in ("HIGH", "CRITICAL"):
                alerts.append({"id": score_id, "score_id": score_id, "severity": row["risk_tier"]})
        for table, rows in [(DailyBehavior, behaviors), (DailyScore, scores), (Alert, alerts)]:
            for start in range(0, len(rows), 200): db.execute(insert(table).values(rows[start:start + 200]))
        db.add(AuditLog(actor="owner-requested-publication", action="model.stage", target=VERSION,
                        details={"dataset_id": report["dataset"]["dataset_id"], "active": False, "windows": len(frame)}))


def activate(factory):
    with factory.begin() as db:
        row = db.get(ModelVersion, VERSION)
        if row is None: raise ValueError("Stage the frozen model before activation")
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:dataset))"), {"dataset": row.dataset_id})
        previous = list(db.scalars(select(ModelVersion.id).where(ModelVersion.dataset_id == row.dataset_id, ModelVersion.active)))
        db.execute(update(ModelVersion).where(ModelVersion.dataset_id == row.dataset_id).values(active=False))
        db.flush()
        db.execute(update(ModelVersion).where(ModelVersion.id == VERSION).values(active=True))
        db.add(AuditLog(actor="owner-requested-publication", action="model.activate", target=VERSION,
                        details={"previous": previous, "reason": "Owner requested V6 Maximum as main output; reused validation scope retained"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "stage", "activate"])
    args = parser.parse_args()
    if args.action == "build":
        report = build(); print(report["version"], report["primary_metrics"]["confusion_matrix"])
    else:
        engine, factory = database()
        try:
            (stage if args.action == "stage" else activate)(factory)
            print(args.action, VERSION)
        finally:
            engine.dispose()
