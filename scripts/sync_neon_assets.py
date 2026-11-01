"""Upload serving assets to Neon or materialize verified copies for file-based readers."""
from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert

from src.db.models import StoredAsset

ASSET_ROOTS = (
    Path("logs_SPEDIA_annotated_en.csv"),
    Path("data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223"),
    Path("data/spedia/features-temporal"),
    Path("data/spedia/review-v3"),
    Path("data/spedia/replay-realistic-v1"),
    Path("data/inference/context-v1"),
)
REQUIRED_ASSETS = (
    "logs_SPEDIA_annotated_en.csv",
    "data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223/model.joblib",
    "data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223/metrics.json",
    "data/spedia/features-temporal/features.parquet",
    "data/spedia/features-temporal/relationships.parquet",
    "data/spedia/review-v3/replay_manifest.json",
    "data/spedia/review-v3/replay_inputs.parquet",
    "data/spedia/review-v3/replay_events.parquet",
    "data/spedia/review-v3/replay_ground_truth.json",
    "data/spedia/replay-realistic-v1/replay_manifest.json",
    "data/spedia/replay-realistic-v1/replay_inputs.parquet",
    "data/spedia/replay-realistic-v1/replay_events.parquet",
    "data/spedia/replay-realistic-v1/replay_ground_truth.json",
    "data/inference/context-v1/context.json",
    "data/inference/context-v1/events.parquet",
)


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def _asset_files(root: Path) -> list[tuple[str, Path]]:
    found: dict[str, Path] = {}
    for configured in ASSET_ROOTS:
        path = root / configured
        if path.is_file():
            found[configured.as_posix()] = path
        elif path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_file() and not candidate.is_symlink() and not candidate.name.endswith(".tmp"):
                    found[candidate.relative_to(root).as_posix()] = candidate
        else:
            raise FileNotFoundError(f"Required asset source is missing: {configured}")
    missing = sorted(set(REQUIRED_ASSETS) - found.keys())
    if missing:
        raise FileNotFoundError("Required serving assets are missing: " + ", ".join(missing))
    return sorted(found.items())


def upload(root: Path) -> None:
    files = _asset_files(root)
    engine = create_engine(_database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 15})
    total_bytes = 0
    try:
        for asset_key, path in files:
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            statement = insert(StoredAsset).values(
                asset_key=asset_key,
                sha256=digest,
                size_bytes=len(content),
                media_type=media_type,
                content=content,
                updated_at=datetime.now(timezone.utc),
            ).on_conflict_do_update(
                index_elements=[StoredAsset.asset_key],
                set_={
                    "sha256": digest,
                    "size_bytes": len(content),
                    "media_type": media_type,
                    "content": content,
                    "updated_at": datetime.now(timezone.utc),
                },
                where=StoredAsset.sha256 != digest,
            )
            with engine.begin() as connection:
                connection.execute(statement)
            total_bytes += len(content)
            print(f"Stored {asset_key} ({len(content)} bytes, sha256 {digest[:12]}…)")
    finally:
        engine.dispose()
    print(f"Stored {len(files)} serving assets ({total_bytes} bytes) in PostgreSQL.")


def materialize(root: Path, cache: Path) -> None:
    engine = create_engine(_database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 15})
    cache_root = cache.resolve()
    written = 0
    total_bytes = 0
    try:
        with engine.connect() as connection:
            assets = connection.execute(
                select(StoredAsset.asset_key, StoredAsset.sha256, StoredAsset.size_bytes)
                .order_by(StoredAsset.asset_key)
            ).mappings().all()
            keys = [asset["asset_key"] for asset in assets]
            missing = sorted(set(REQUIRED_ASSETS) - set(keys))
            if missing:
                raise RuntimeError("Neon asset store is incomplete: " + ", ".join(missing))
            for asset in assets:
                asset_key = asset["asset_key"]
                relative = Path(asset_key)
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError(f"Unsafe asset path in Neon: {asset_key}")
                destination = (cache_root / relative).resolve()
                if not destination.is_relative_to(cache_root):
                    raise RuntimeError(f"Asset path escapes cache root: {asset_key}")
                if destination.is_file() and destination.stat().st_size == asset["size_bytes"]:
                    current = hashlib.sha256(destination.read_bytes()).hexdigest()
                    if current == asset["sha256"]:
                        total_bytes += asset["size_bytes"]
                        continue
                row = connection.execute(
                    select(StoredAsset.content).where(StoredAsset.asset_key == asset_key)
                ).scalar_one()
                digest = hashlib.sha256(row).hexdigest()
                if digest != asset["sha256"] or len(row) != asset["size_bytes"]:
                    raise RuntimeError(f"Neon asset integrity check failed: {asset_key}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".tmp")
                temporary.write_bytes(row)
                os.replace(temporary, destination)
                written += 1
                total_bytes += asset["size_bytes"]
    finally:
        engine.dispose()
    print(f"Verified {len(keys)} Neon assets ({total_bytes} bytes); refreshed {written} cache files.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upload", "materialize"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--cache", type=Path, default=Path("data/runtime/neon-assets"))
    args = parser.parse_args()
    try:
        if args.action == "upload":
            upload(args.root.resolve())
        else:
            materialize(args.root.resolve(), args.cache if args.cache.is_absolute() else args.root / args.cache)
    except Exception as error:
        print(f"Asset synchronization failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
