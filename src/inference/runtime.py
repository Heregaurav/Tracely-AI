"""Resolve versioned serving assets without replacing historical configurations."""
from src.data.neon_assets import resolve_asset_path


def model_directory(model, key, fallback):
    configured = model.report.get("runtime_assets", {}).get(key)
    return str(resolve_asset_path(configured)) if configured else fallback
