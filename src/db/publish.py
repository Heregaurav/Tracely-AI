"""Atomic publication of verified offline results, preserving previous versions."""
import hashlib
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from src.data.integrity import sha256_file
from .models import (Alert, AuditLog, DailyBehavior, DailyScore, Dataset, ModelVersion,
                     Principal, Relationship)


def publish_run(factory, run_directory, *, actor="offline-import", allow_fixture=False, activate=True):
    root = Path(run_directory).resolve()
    report = json.loads((root / "metrics.json").read_text())
    if report["is_fixture"] and not allow_fixture:
        raise ValueError("Fixture models cannot be published unless explicitly enabled for an isolated test/development deployment")
    if sha256_file(root / "model.joblib") != report["artifact_sha256"]:
        raise ValueError("Artifact checksum mismatch")
    if sha256_file(root / "scores.parquet") != report["scores_sha256"]:
        raise ValueError("Scored-record checksum mismatch")
    frame = pd.read_parquet(root / "scores.parquet")
    dataset_id, version = report["dataset"]["dataset_id"], report["version"]
    if set(frame.dataset_id) != {dataset_id} or set(frame.model_version) != {version}:
        raise ValueError("Scored records do not match dataset/model version")
    definition = report['contract']
    if definition.get('window_seconds') != 3600 or definition.get('scoring_unit') != 'user-nonoverlapping-hour':
        raise ValueError('Unsupported feature contract: expected normalized closed user-hours')
    feature_version = definition['version']
    names = [f['name'] for f in definition['features']]
    if not names or len(names) != len(set(names)) or set(names)-set(frame.columns):
        raise ValueError('Invalid ordered feature contract')
    ordinal = 'window_index'
    with factory.begin() as db:
        # Transaction advisory lock serializes publication per dataset (all workers).
        from sqlalchemy import text
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:dataset))"), {"dataset": dataset_id})
        existing = db.get(ModelVersion, version)
        if existing:
            if existing.artifact_sha256 != report["artifact_sha256"]:
                raise ValueError("Existing version has different bytes")
            return version
        db.execute(insert(Dataset).values(id=dataset_id, provenance=report["dataset"]["provenance"],
                                         is_fixture=report["is_fixture"]).on_conflict_do_nothing())
        db.execute(update(Dataset).where(Dataset.id==dataset_id).values(provenance=report["dataset"]["provenance"]))
        db.add(ModelVersion(id=version, dataset_id=dataset_id, feature_version=feature_version,
                            artifact_path=str(root), artifact_sha256=report["artifact_sha256"], report=report, active=False))
        db.flush()
        for row in frame.to_dict("records"):
            db.execute(insert(Principal).values(dataset_id=dataset_id, user=row["user"]).on_conflict_do_nothing())
            key = {"dataset_id": dataset_id, "user": row["user"], "relative_day": int(row[ordinal]), "feature_version": feature_version}
            values = {name: float(row[name]) for name in names}
            previous = db.get(DailyBehavior, tuple(key.values()))
            if previous is not None and previous.values != values:
                raise ValueError("Conflicting immutable user-hour features; use a new dataset identifier or feature version")
            db.execute(insert(DailyBehavior).values(**key, values=values).on_conflict_do_nothing())
            score_id = hashlib.sha256(f"{dataset_id}|{version}|{row['user']}|{row[ordinal]}".encode()).hexdigest()
            db.add(DailyScore(id=score_id, **key, model_version=version,
                              risk_score=float(row["risk_score"]), risk_tier=row["risk_tier"],
                              components={name: float(row[name]) for name in row if name.endswith("_score") and name != "risk_score"},
                              explanation=json.loads(row["explanation"])))
            db.flush()
            if row["risk_tier"] in ("HIGH", "CRITICAL"):
                db.add(Alert(id=score_id, score_id=score_id, severity=row["risk_tier"]))
        # Adapters publish normalized observed user/host relationships.
        path=Path(report['dataset']['relationships_path'])
        if sha256_file(path)!=report['dataset']['relationships_sha256']:
            raise ValueError('Relationship checksum mismatch')
        for r in pd.read_parquet(path).itertuples():
            db.execute(insert(Relationship).values(dataset_id=dataset_id,user=r.user,relative_day=int(r.window_index),
                source_computer=r.host,destination_computer=r.host,weight=int(r.weight)).on_conflict_do_nothing())
        if activate:
            db.execute(update(ModelVersion).where(ModelVersion.dataset_id == dataset_id).values(active=False))
            db.flush()
            db.execute(update(ModelVersion).where(ModelVersion.id == version).values(active=True))
        db.add(AuditLog(actor=actor, action="model.publish", target=version, details={"activate": activate, "dataset_id": dataset_id}))
    return version
