"""Prespecified normal-only behavioral experiments, never production activation.

All new fitting, early stopping and calibration use earlier original TRAIN hours.
The already reused original validation is diagnostic only. No attack-validity
claim is possible when source and annotations are perfectly confounded.
"""
from __future__ import annotations
import argparse
import copy
from dataclasses import dataclass, field
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import RobustScaler

from src.data.integrity import sha256_file
from src.data.spedia import FEATURE_NAMES, load_spedia, prepare_events
from src.data.spedia_behavioral_v6 import NAMES, PERSONAL, VERSION, contract, features_for_windows
from src.evaluation.spedia_origin_audit import FROZEN, FORBIDDEN, distribution, evaluate_known, fit_origin_classifier, source_windows, write_json
from src.models.scoring import percentile_scores

BUDGETS = (10., 50.)


def budget_threshold(values, budget):
    values = np.asarray(values, float)
    if not len(values) or not np.isfinite(values).all() or not 0 <= budget <= 1000:
        raise ValueError('Finite calibration and valid normal alert budget required')
    maximum = int(np.floor(len(values) * budget / 1000))
    levels = np.unique(values)
    counts = len(values) - np.searchsorted(np.sort(values), levels, side='left')
    eligible = np.flatnonzero(counts <= maximum)
    threshold = float(levels[eligible[0]]) if len(eligible) else float(np.nextafter(values.max(), np.inf))
    count = int((values >= threshold).sum())
    return threshold, {'normal_calibration_hours': len(values), 'target_alerts_per_1000_hours': budget,
                       'maximum_alerts': maximum, 'observed_alerts': count,
                       'actual_alerts_per_1000_hours': count / len(values) * 1000,
                       'threshold_in_calibration_values': bool(len(eligible)),
                       'normal_tail_resolution_per_1000': 1000 / len(values)}


def split_normal_training(frame):
    """Split complete timestamps; never accept an evaluation row as fit data."""
    if set(frame.split) != {'train'}:
        raise ValueError('Fit/early-stop/calibration must come only from original train')
    normal = frame.loc[frame.label.eq(False)].sort_values(['window_start', 'user']).copy()
    if normal.window_id.duplicated().any() or frame.label.isna().any():raise ValueError('Invalid training identities/labels')
    times = pd.to_datetime(normal.window_start)
    a = times.iloc[int(len(normal) * .7)]; b = times.iloc[int(len(normal) * .85)]
    parts = {'fit': normal.loc[times < a].copy(), 'early_stop': normal.loc[(times >= a) & (times < b)].copy(),
             'calibration': normal.loc[times >= b].copy()}
    if min(map(len, parts.values())) < 10:raise ValueError('Insufficient independent chronological normal subsets')
    assert max(pd.to_datetime(parts['fit'].window_start)) < min(pd.to_datetime(parts['early_stop'].window_start))
    assert max(pd.to_datetime(parts['early_stop'].window_start)) < min(pd.to_datetime(parts['calibration'].window_start))
    return parts


def signed_log(x):return np.sign(x) * np.log1p(np.abs(x))


@dataclass
class ExperimentalDetector:
    """Separate research contract; intentionally not a deployable BehavioralDetector."""
    names: list[str]
    kind: str
    feature_version: str = VERSION
    scaler: object = None
    estimator: object = None
    reference: object = None
    thresholds: dict = field(default_factory=dict)
    neural_history: list = field(default_factory=list)

    def matrix(self, frame):
        if set(self.names) & FORBIDDEN or len(set(self.names)) != len(self.names) or not set(self.names) <= set(frame):
            raise ValueError('Experimental feature contract mismatch')
        x = frame[self.names].to_numpy(dtype=float)
        if not np.isfinite(x).all():raise ValueError('Nonfinite experimental inputs')
        return x

    def raw(self, frame):
        x = self.matrix(frame)
        if self.kind == 'personal_volume':result = np.abs(frame.personal_volume_mad_z_7d.to_numpy(float))
        elif self.kind == 'activity_mix':result = frame.activity_mix_l1_change_7d.to_numpy(float)
        else:
            x = self.scaler.transform(signed_log(x))
            if self.kind == 'if':result = -self.estimator.score_samples(x)
            elif self.kind == 'pca':result = np.mean((x - self.estimator.inverse_transform(self.estimator.transform(x))) ** 2, axis=1)
            elif self.kind == 'ae':result = np.mean((x - self.estimator.predict(x)) ** 2, axis=1)
            else:raise ValueError('Unsupported research model')
        if not np.isfinite(result).all():raise ValueError('Nonfinite research score')
        return result

    def predict_indices(self, frame, *, feature_version):
        if feature_version != self.feature_version:raise ValueError('Feature version mismatch')
        if self.reference is None:raise ValueError('Frozen normal calibration reference required')
        return percentile_scores(self.raw(frame), self.reference)


def fit_candidate(kind, names, parts, epochs):
    if set(parts) != {'fit', 'early_stop', 'calibration'}:
        raise ValueError('Explicit fit, early-stop and calibration subsets required')
    for frame in parts.values():
        if set(frame.split) != {'train'} or frame.label.isna().any() or frame.label.astype(bool).any():
            raise ValueError('Only known-normal original training observations may fit or calibrate')
    ids = [set(parts[k].window_id) for k in ('fit', 'early_stop', 'calibration')]
    if any(ids[i] & ids[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError('Training subsets overlap')
    if not (pd.to_datetime(parts['fit'].window_start).max() < pd.to_datetime(parts['early_stop'].window_start).min()
            <= pd.to_datetime(parts['early_stop'].window_start).max() < pd.to_datetime(parts['calibration'].window_start).min()):
        raise ValueError('Training subsets must be chronological')
    model = ExperimentalDetector(list(names), kind)
    if kind not in ('personal_volume', 'activity_mix'):
        x = signed_log(model.matrix(parts['fit']))
        model.scaler = RobustScaler().fit(x)
        x = model.scaler.transform(x)
        if kind == 'if':model.estimator = IsolationForest(n_estimators=200, max_samples='auto', random_state=42, n_jobs=1).fit(x)
        elif kind == 'pca':model.estimator = PCA(n_components=max(1, min(len(names) // 2, len(x) - 1)), random_state=42).fit(x)
        else:
            early = model.scaler.transform(signed_log(model.matrix(parts['early_stop'])))
            network = MLPRegressor(hidden_layer_sizes=(24, 8, 24), activation='relu', alpha=.001, solver='adam',
                                   learning_rate_init=.001, batch_size=min(64, len(x)), shuffle=False, random_state=42)
            best = float('inf'); stale = 0
            for epoch in range(epochs):
                network.partial_fit(x, x)
                loss = float(np.mean((network.predict(early) - early) ** 2))
                model.neural_history.append({'epoch': epoch + 1, 'normal_early_stop_mse': loss})
                if loss < best - 1e-6:best = loss; model.estimator = copy.deepcopy(network); stale = 0
                else:stale += 1
                if stale >= 8:break
            if model.estimator is None:raise ValueError('No finite AE checkpoint')
    model.reference = np.sort(model.raw(parts['calibration']))
    calibration_indices = model.predict_indices(parts['calibration'], feature_version=VERSION)
    for budget in BUDGETS:
        threshold, _ = budget_threshold(calibration_indices, budget)
        model.thresholds[str(budget)] = threshold
    return model


def validate_external_cohort(features, labels, manifest, forbidden_window_ids=()):
    """Evidence gate for a future independent collection; cannot prove attestations."""
    if manifest.get('feature_version') != VERSION or manifest.get('telemetry_profile') != 'spedia-v2-native':
        raise ValueError('External feature and native telemetry semantics must match')
    review = manifest.get('independence_review', {})
    if not review.get('approved') or not review.get('reviewer') or not review.get('evidence'):
        raise ValueError('Independent provenance/label review required; cannot infer independence')
    required = {'window_id', 'label', 'generation_process_id', 'scenario_id', 'participant_id'}
    if not required <= set(labels):raise ValueError('Verified label/process/scenario/participant metadata required')
    if labels.window_id.duplicated().any() or features.window_id.duplicated().any():raise ValueError('Duplicate external windows')
    if not set(features.window_id) == set(labels.window_id):raise ValueError('Complete window membership required')
    if set(features.window_id) & set(forbidden_window_ids):raise ValueError('External observations overlap examined SPEDIA windows')
    if labels.label.isna().any() or not labels.label.isin([0, 1, False, True]).all():raise ValueError('Known labels required; retain unknown rows outside the scored cohort')
    if labels[list(required - {'label'})].isna().any().any():raise ValueError('Missing verified grouping identity')
    if (labels.groupby('generation_process_id').label.nunique() < 2).any():raise ValueError('Both labels within every verified generation process are required')
    if not set(NAMES) <= set(features) or not np.isfinite(features[NAMES].to_numpy(float)).all():raise ValueError('External feature contract mismatch')
    return {'eligible_for_predeclared_evaluation': True, 'warning': 'Review attestations, original record/payload non-overlap, sealed hashes, participant/scenario grouping and native-unit compatibility still require independent verification.'}


def _record(name, indices, cal, raw, validation, bundle, output):
    result = {'scope': 'Reused development validation; not independent threat performance',
              'kind': bundle.kind if bundle else name, 'feature_names': bundle.names if bundle else None,
              'budgets': {}, 'raw_validation_quantiles': distribution(raw),
              'source_score_associations': {cohort: distribution(indices[validation.origin_cohort.eq(cohort).to_numpy()]) for cohort in validation.origin_cohort.unique()}}
    for budget in BUDGETS:
        threshold, calibration = budget_threshold(cal, budget)
        result['budgets'][str(budget)] = {**evaluate_known(validation.label, indices, threshold), 'calibration': calibration}
    output_frame = validation[['window_id', 'user', 'window_start', 'label', 'origin_cohort']].copy()
    output_frame['raw_score'] = raw; output_frame['index'] = indices
    output_frame.to_parquet(output / (name + '_validation.parquet'), index=False)
    return result


def score_candidate(report, name, frame, root, *, feature_version=VERSION):
    """Read-only replay of a trusted research candidate or its fixed ensemble."""
    from src.inference.artifacts import load_verified_model
    if feature_version != VERSION:raise ValueError('Feature version mismatch')
    record = report['candidates'][name]
    if 'artifact' in record:
        model = load_verified_model(Path(root) / record['artifact'], record['artifact_sha256'])
        if not isinstance(model, ExperimentalDetector):raise ValueError('Unexpected research artifact type')
        return model.predict_indices(frame, feature_version=feature_version)
    if 'members' not in record:raise ValueError('Unknown research candidate contract')
    a, b = [score_candidate(report, member, frame, root, feature_version=feature_version) for member in record['members']]
    return np.maximum(a, b) if name.endswith('_max') else .6 * a + .4 * b


def run_experiment(output, epochs=50):
    out = Path(output)
    if not (out / 'audit_metrics.json').exists():raise ValueError('Complete origin audit before experimental fitting')
    experiment = out / 'experiment'
    experiment.mkdir(exist_ok=False)
    saved = pd.read_parquet(FROZEN / 'scores.parquet')
    raw = load_spedia('logs_SPEDIA_annotated_en.csv'); events, _ = prepare_events(raw)
    development = saved.loc[saved.split.isin(['train', 'validation'])].copy()
    forbidden = set(saved.loc[saved.split == 'test', 'window_id'])
    wanted = {rid for ids in development.record_ids for rid in ids}
    forbidden_events = {rid for ids in saved.loc[saved.split == 'test', 'record_ids'] for rid in ids}
    assert wanted.isdisjoint(forbidden_events)
    # Include pre-vector-purge earlier context; exclude all old test timestamps.
    dev_events = events.loc[events.time < pd.Timestamp('2025-03-26')].copy()
    assert set(dev_events.source_record_id).isdisjoint(forbidden_events)
    frame = features_for_windows(dev_events, source_windows(raw, development))
    train = frame.loc[frame.split == 'train']; val = frame.loc[frame.split == 'validation']
    parts = split_normal_training(train)
    representations = {'base_30': FEATURE_NAMES, 'behavior_55': NAMES, 'personal_22': PERSONAL}
    split_manifest = {key: {'windows': len(g), 'window_ids': g.window_id.tolist(),
                            'start': str(g.window_start.min()), 'end': str(g.window_start.max())} for key, g in parts.items()}
    assert all(set(g.window_id).isdisjoint(forbidden) for g in [*parts.values(), val])
    plan = {'feature_contract': contract(), 'seed': 42, 'max_epochs': epochs, 'representations': representations,
            'models': ['if', 'pca', 'ae'], 'fixed_ensembles': {'if_ae_mean': [.6, .4], 'if_ae_max': 'maximum of two indices'},
            'normal_alert_budgets_per_1000': BUDGETS, 'training_subsets': split_manifest,
            'development_validation_window_ids': val.window_id.tolist(), 'old_test_fitting_or_scoring': False,
            'selection': 'No winner selected. No attack-label hyperparameter or threshold tuning.',
            'reason_for_representations': 'Preserve all base behavior; compare additional within-account changes and a prespecified ratio/change subset. None is asserted source invariant.',
            'limits': 'Normal fit/early-stop/calibration use disjoint chronological original-train timestamps; few calibration rows limit tail precision. Reused development validation labels remain perfectly origin-confounded.'}
    write_json(experiment / 'plan.json', plan)  # Saved before any candidate fitting.
    frame.drop(columns=['scenario_proxies']).to_parquet(experiment / 'development_features.parquet', index=False)
    results = {}; components = {}; source_association = {}
    for representation, names in representations.items():
        origin, diagnostic = fit_origin_classifier(train, val, names, repeats=5)
        source_association[representation] = origin
        if diagnostic:
            diagnostic['feature_version'] = VERSION
            joblib.dump(diagnostic, experiment / (representation + '_source_diagnostic.joblib'), compress=3)
        components[representation] = {}
        for kind in ('if', 'pca', 'ae'):
            name = representation + '_' + kind
            model = fit_candidate(kind, names, parts, epochs)
            raw_cal = model.raw(parts['calibration']); raw_val = model.raw(val)
            cal = model.predict_indices(parts['calibration'], feature_version=VERSION)
            index = model.predict_indices(val, feature_version=VERSION)
            state = joblib.hash(model)
            path = experiment / (name + '.joblib'); joblib.dump(model, path, compress=3)
            restored = joblib.load(path)
            np.testing.assert_array_equal(index, restored.predict_indices(val, feature_version=VERSION))
            assert state == joblib.hash(model)
            record = _record(name, index, cal, raw_val, val, model, experiment)
            record.update(artifact=path.name, artifact_sha256=sha256_file(path), feature_version=VERSION,
                          scaler_fit_windows=parts['fit'].window_id.tolist(), neural_history=model.neural_history,
                          serialized_replay_exact=True, calibration_raw_quantiles=distribution(raw_cal))
            results[name] = record; components[representation][kind] = (index, cal)
            print('Experimental fitted and replayed:', name, flush=True)
        for aggregation in ('mean', 'max'):
            name = representation + '_if_ae_' + aggregation
            a, c = components[representation]['if']; b, d = components[representation]['ae']
            index, cal = (.6 * a + .4 * b, .6 * c + .4 * d) if aggregation == 'mean' else (np.maximum(a, b), np.maximum(c, d))
            results[name] = _record(name, index, cal, index, val, None, experiment)
            results[name]['members'] = [representation + '_if', representation + '_ae']
            results[name]['score_units'] = 'Calibrated component-index fusion; no single raw reconstruction score'
    for kind, name in [('personal_volume', 'interpretable_personal_volume'), ('activity_mix', 'interpretable_activity_mix')]:
        model = fit_candidate(kind, PERSONAL, parts, epochs)
        index = model.predict_indices(val, feature_version=VERSION)
        cal = model.predict_indices(parts['calibration'], feature_version=VERSION)
        joblib.dump(model, experiment / (name + '.joblib'), compress=3)
        results[name] = _record(name, index, cal, model.raw(val), val, model, experiment)
        results[name].update(artifact=name + '.joblib', artifact_sha256=sha256_file(experiment / (name + '.joblib')), feature_version=VERSION, serialized_replay_exact=True)
        restored = joblib.load(experiment / (name + '.joblib'))
        np.testing.assert_array_equal(index, restored.predict_indices(val, feature_version=VERSION))
    report = {'plan': plan, 'candidates': results, 'source_prediction_by_representation': source_association,
              'fixed_frozen_v2_validation': evaluate_known(val.label, val.risk_score, 93.11764705882352),
              'v5_comparison': json.loads(Path('data/spedia/experiment-v5/report.json').read_text())['results'],
              'genuine_behavior_improvement_established': False,
              'reason': 'No same-generation-process mixed-label cohort or independent compatible data exists. Improved label metrics cannot distinguish origin discrimination from threat detection.',
              'activation_or_publication': False}
    write_json(experiment / 'experimental_metrics.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--epochs', type=int, default=50)
    args = parser.parse_args()
    from src.evaluation.spedia_behavioral_v6 import run_experiment as run_canonical
    run_canonical(args.output, args.epochs)
