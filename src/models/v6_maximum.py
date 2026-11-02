"""Inference-only adapter for the frozen, previously fitted V6 maximum ensemble."""
from dataclasses import dataclass

import numpy as np

from src.data.spedia import contract as base_contract
from src.data.spedia_behavioral_v6 import DEFINITIONS, NAMES, VERSION
from src.models.scoring import TIERS, percentile_scores


def serving_contract():
    definition = base_contract()
    definition.update(version=VERSION, base_contract="spedia-hour-v1")
    definition["features"] += [
        {"name": name, "dtype": "float64", "training": True, "inference": True,
         "source": description, "window": "Current closed hour and strictly earlier history"}
        for name, description in DEFINITIONS.items()
    ]
    # DEFINITIONS is descriptive; the numerical order is the saved NAMES order.
    by_name = {item["name"]: item for item in definition["features"]}
    definition["features"] = [by_name[name] for name in NAMES]
    return definition


@dataclass
class V6MaximumDetector:
    names: list
    forest: object
    forest_scaler: object
    forest_reference: object
    neural: object
    neural_scaler: object
    neural_reference: object
    threshold: float
    feature_version: str = VERSION
    active: str = "behavior_55_if_ae_max"

    @property
    def cutoffs(self):
        return [.4 * self.threshold, .8 * self.threshold,
                self.threshold, (self.threshold + 100) / 2]

    def score(self, frame):
        if self.names != NAMES or not set(self.names).issubset(frame.columns):
            raise ValueError("V6 maximum requires its ordered 55-feature contract")
        values = frame.loc[:, self.names].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("V6 inputs must be finite")
        transformed = np.sign(values) * np.log1p(np.abs(values))
        forest_values = self.forest_scaler.transform(transformed)
        neural_values = self.neural_scaler.transform(transformed)
        if_index = percentile_scores(-self.forest.score_samples(forest_values), self.forest_reference)
        neural_raw = np.mean((neural_values - self.neural.predict(neural_values)) ** 2, axis=1)
        neural_index = percentile_scores(neural_raw, self.neural_reference)
        index = np.maximum(if_index, neural_index)
        tiers = np.asarray(TIERS)[np.searchsorted(self.cutoffs, index, side="right")]
        return index, tiers, {"if_score": if_index, "neural_score": neural_index}
