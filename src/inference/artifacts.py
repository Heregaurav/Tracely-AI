"""Load trusted local frozen artifacts only after checking their recorded digest."""
from pathlib import Path
import joblib
from src.data.integrity import sha256_file


def load_verified_model(path, expected_sha256, *, error_type=ValueError):
    """Never accepts an HTTP upload. Preserve caller-specific validation errors."""
    path = Path(path)
    if sha256_file(path) != expected_sha256:
        raise error_type('Frozen model checksum mismatch')
    return joblib.load(path)
