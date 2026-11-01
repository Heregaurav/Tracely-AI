"""Resolve database-backed immutable serving assets to verified local cache paths."""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


def resolve_asset_path(path: str | Path) -> Path:
    """Return a runtime path, mapping repository data paths to the Neon cache."""
    value = Path(path)
    if os.getenv("ASSET_STORAGE") != "postgres":
        return value

    if value.is_absolute():
        parts = value.parts
        try:
            index = parts.index("data")
        except ValueError as error:
            raise ValueError("Database-backed asset path must be under the data directory") from error
        relative = PurePosixPath(*parts[index:])
    else:
        relative = PurePosixPath(value.as_posix())

    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Invalid database-backed asset path")

    cache_root = Path(os.getenv("ASSET_CACHE_ROOT", "data/runtime/neon-assets"))
    resolved_root = cache_root.resolve()
    resolved_path = (resolved_root / Path(*relative.parts)).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError("Database-backed asset path escapes the cache directory")
    return resolved_path
