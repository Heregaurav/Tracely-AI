from pathlib import Path

import pytest

from src.data.neon_assets import resolve_asset_path


def test_local_storage_keeps_existing_path(monkeypatch, tmp_path):
    path = Path("data/spedia/features-temporal/features.parquet")
    monkeypatch.delenv("ASSET_STORAGE", raising=False)
    assert resolve_asset_path(path) == path


def test_postgres_storage_maps_repository_paths_into_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ASSET_STORAGE", "postgres")
    monkeypatch.setenv("ASSET_CACHE_ROOT", str(tmp_path / "cache"))

    relative = resolve_asset_path("data/spedia/review-v3/replay_inputs.parquet")
    absolute = resolve_asset_path("/srv/tracely/data/artifacts/model/model.joblib")

    assert relative == tmp_path / "cache/data/spedia/review-v3/replay_inputs.parquet"
    assert absolute == tmp_path / "cache/data/artifacts/model/model.joblib"


def test_postgres_storage_rejects_paths_outside_data(monkeypatch, tmp_path):
    monkeypatch.setenv("ASSET_STORAGE", "postgres")
    monkeypatch.setenv("ASSET_CACHE_ROOT", str(tmp_path / "cache"))

    with pytest.raises(ValueError, match="under the data directory"):
        resolve_asset_path("/etc/passwd")


def test_postgres_storage_rejects_parent_traversal(monkeypatch, tmp_path):
    monkeypatch.setenv("ASSET_STORAGE", "postgres")
    monkeypatch.setenv("ASSET_CACHE_ROOT", str(tmp_path / "cache"))

    with pytest.raises(ValueError, match="Invalid database-backed asset path"):
        resolve_asset_path("data/../../etc/passwd")
