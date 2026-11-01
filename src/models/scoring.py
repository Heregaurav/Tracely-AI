"""Dataset-independent frozen percentile calibration and explicit ensemble scoring."""
import numpy as np

TIERS = ("NORMAL", "LOW", "MEDIUM", "HIGH", "CRITICAL")


def percentile_scores(values, reference):
    reference = np.sort(np.asarray(reference, dtype=float))
    if len(reference) == 0 or not np.isfinite(reference).all():
        raise ValueError("Nonempty finite calibration reference required")
    values = np.asarray(values, dtype=float)
    return (np.searchsorted(reference, values, side="left") + np.searchsorted(reference, values, side="right")) / (2*len(reference)) * 100


def combine(components, weights):
    if not weights or set(weights) != set(components):
        raise ValueError("Explicit weights must match the available signals")
    if any(not np.isfinite(w) or w < 0 for w in weights.values()) or not np.isclose(sum(weights.values()), 1):
        raise ValueError("Weights must be finite, nonnegative, and sum to one")
    arrays = [np.asarray(components[name], dtype=float) for name in weights]
    if any(a.shape != arrays[0].shape or not np.isfinite(a).all() or ((a < 0) | (a > 100)).any() for a in arrays):
        raise ValueError("Signals must share shape and contain finite indices in [0,100]")
    return sum(weights[name] * np.asarray(components[name]) for name in weights)
