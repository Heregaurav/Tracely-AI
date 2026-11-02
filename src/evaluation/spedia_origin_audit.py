"""Origin association audit and frozen diagnostics; never changes serving artifacts.

An origin classifier measures source predictability, not malicious behavior.
Existing examined test observations are descriptive only, never fitting inputs.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.data.integrity import sha256_file
from src.data.spedia import FEATURE_NAMES, aggregate_windows, load_spedia, prepare_events
from src.inference.artifacts import load_verified_model

FROZEN = Path('data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223')
FORBIDDEN = {'Anomaly', 'label', 'Agent_name', 'User', 'Timestamp', 'Decoder_name',
             'simulation_marker', 'cert_tag', 'scenario_proxy', 'Description',
             'Full_log', 'Content', 'Level', 'origin', 'window_id', 'source_record_id'}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, default=str, allow_nan=False))


def evaluate_known(y, score, threshold=None):
    """Single-class cohorts have workload/coverage, not invented discrimination."""
    labels = pd.Series(y)
    if labels.isna().any() or not labels.isin([0, 1, False, True]).all():
        raise ValueError('Explicit known binary labels required; never impute unknown labels')
    y = labels.to_numpy(dtype=bool)
    s = np.asarray(score, dtype=float)
    if not len(y) or s.shape != y.shape or not np.isfinite(s).all():
        raise ValueError('Finite nonempty aligned scores required')
    both = len(np.unique(y)) == 2
    result = {'windows': len(y), 'positive': int(y.sum()), 'negative': int((~y).sum()),
              'average_precision': float(average_precision_score(y, s)) if both else None,
              'roc_auc': float(roc_auc_score(y, s)) if both else None,
              'precision': None, 'recall': None, 'f1': None, 'threshold': threshold,
              'single_class_discrimination_unavailable': not both}
    if threshold is not None:
        if not np.isfinite(threshold):
            raise ValueError('Finite threshold required')
        pred = s >= threshold
        tn, fp, fn, tp = map(int, confusion_matrix(y, pred, labels=[False, True]).ravel())
        p = tp / (tp + fp) if tp + fp else 0.
        r = tp / (tp + fn) if tp + fn else 0.
        result.update(confusion_matrix=[[tn, fp], [fn, tp]], alerts=int(pred.sum()),
                      false_positive_rate=fp / int((~y).sum()) if (~y).any() else None,
                      false_alerts_per_1000_hours=fp / len(y) * 1000,
                      alerts_per_1000_hours=float(pred.mean() * 1000),
                      positive_hour_coverage=tp / int(y.sum()) if y.any() else None)
        if both:
            result.update(precision=p, recall=r, f1=2 * p * r / (p + r) if p + r else 0.)
    return result


def distribution(values):
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    return {'finite': len(x), 'mean': float(x.mean()) if len(x) else None,
            'quantiles': {str(q): float(np.quantile(x, q)) for q in (0, .25, .5, .75, .9, .99, 1)} if len(x) else {}}


def source_windows(events, windows):
    """Origin comes from raw marker metadata; mixed windows stay a third cohort."""
    if events.source_record_id.duplicated().any() or windows.window_id.duplicated().any():
        raise ValueError('Ambiguous record/window identities')
    source = (~events.set_index('source_record_id').simulation_marker).astype(int)
    proxy = events.set_index('source_record_id').scenario_proxy
    available_ids = set(source.index)
    records = []
    for r in windows.itertuples():
        ids = list(r.record_ids)
        if not set(ids) <= available_ids:
            raise ValueError('Missing origin provenance for an evaluation record')
        values = source.loc[ids].to_numpy()
        fraction = float(values.mean())
        cohort = 'simulation_only' if fraction == 0 else 'non_simulation_only' if fraction == 1 else 'mixed'
        records.append({'window_id': r.window_id, 'origin_fraction_non_simulation': fraction,
                        'origin_cohort': cohort, 'scenario_proxies': sorted(set(proxy.loc[ids].dropna()))})
    return windows.merge(pd.DataFrame(records), on='window_id', validate='one_to_one')


def fit_origin_classifier(train, validation, names, repeats=10):
    """Fixed C=1 logistic source diagnostic, chronological train -> validation."""
    if set(names) & FORBIDDEN or len(names) != len(set(names)):
        raise ValueError('Origin/annotation metadata cannot enter the numerical matrix')
    if set(train.split) != {'train'} or set(validation.split) != {'validation'}:
        raise ValueError('Origin fitting must use original train and validation partitions only')
    a = train.loc[train.origin_cohort != 'mixed'].copy()
    b = validation.loc[validation.origin_cohort != 'mixed'].copy()
    y_a = a.origin_cohort.eq('non_simulation_only').astype(int)
    y_b = b.origin_cohort.eq('non_simulation_only').astype(int)
    if y_a.nunique() < 2 or y_b.nunique() < 2:
        return {'available': False, 'reason': 'Both origins required in train and validation'}, None
    if not pd.to_datetime(a.window_start).max() < pd.to_datetime(b.window_start).min():
        raise ValueError('Source diagnostic must be strictly chronological')
    overlap = set(a.window_id) & set(b.window_id)
    train_proxies = {p for values in a.scenario_proxies for p in values}
    val_proxies = {p for values in b.scenario_proxies for p in values}
    if overlap or train_proxies & val_proxies:
        raise ValueError('Source diagnostic overlaps window identities or known scenario proxies')
    x_a = a[names].to_numpy(float); x_b = b[names].to_numpy(float)
    if not np.isfinite(x_a).all() or not np.isfinite(x_b).all():
        raise ValueError('Source diagnostic features must be finite')
    classifier = make_pipeline(StandardScaler(), LogisticRegression(C=1., class_weight='balanced', max_iter=2000, random_state=42))
    classifier.fit(x_a, y_a)
    score = classifier.predict_proba(x_b)[:, 1]
    permutation = permutation_importance(classifier, x_b, y_b, scoring='roc_auc', n_repeats=repeats, random_state=42, n_jobs=1)
    coefficients = classifier[-1].coef_[0]
    importance = sorted([{'feature': name, 'roc_auc_decrease_mean': float(permutation.importances_mean[i]),
                          'roc_auc_decrease_std': float(permutation.importances_std[i]),
                          'standardized_logistic_coefficient': float(coefficients[i])} for i, name in enumerate(names)],
                        key=lambda r: r['roc_auc_decrease_mean'], reverse=True)
    report = {'available': True, 'task': 'SOURCE prediction, not threat detection', 'training_windows': len(a),
              'validation_windows': len(b), 'excluded_mixed_train': len(train) - len(a),
              'excluded_mixed_validation': len(validation) - len(b),
              'metrics': evaluate_known(y_b, score, .5), 'permutation_associations': importance,
              'fit_window_ids': a.window_id.tolist(), 'validation_window_ids': b.window_id.tolist(),
              'scaler_fit_rows': int(classifier[0].n_samples_seen_),
              'warning': 'Predictive associations are not causal; origin target equals event annotation on pure windows. Known proxy groups disjoint, true scenario identities unknown.'}
    return report, {'model': classifier, 'features': list(names), 'task': report['task'],
                    'feature_version': 'spedia-hour-v1' if names == FEATURE_NAMES else 'v5-development',
                    'fit_window_ids': a.window_id.tolist()}


def _raw_audit(raw, native_columns):
    raw = raw.copy()
    raw['origin'] = np.where(raw.simulation_marker, 'simulation', 'non_simulation')
    result = {'events': len(raw), 'direct_origin_rule_accuracy': float(((~raw.simulation_marker).astype(int) == raw.Anomaly).mean()),
              'source_label_counts': raw.groupby(['origin', 'Anomaly']).size().rename('events').reset_index().to_dict('records'),
              'within_source_class_support': {}, 'variable_audit': [], 'distributions': {}, 'missingness': {}}
    for origin, group in raw.groupby('origin'):
        result['within_source_class_support'][origin] = sorted(group.Anomaly.unique().astype(int).tolist())
        result['missingness'][origin] = group[native_columns].isna().mean().to_dict()
    explicit = {'Agent_name', 'Decoder_name'}
    annotations = {'Anomaly', 'Description', 'Level', 'Full_log', 'Content'}
    identifiers = {'id', 'User', 'From'}
    for column in native_columns:
        # Sample purity is descriptive: UUID/high cardinality can memorize any target.
        grouped = pd.crosstab(raw[column].fillna('<missing>').astype(str), raw.Anomaly)
        purity = float(grouped.max(axis=1).sum() / grouped.to_numpy().sum())
        category = 'annotation/annotation-text risk; excluded' if column in annotations else \
                   'explicit source metadata; excluded' if column in explicit else \
                   'identifier/source-association risk; not numerical input' if column in identifiers else \
                   'behavioral field with possible source proxy; causality unidentifiable'
        result['variable_audit'].append({'variable': column, 'classification': category, 'unique_values': int(raw[column].nunique()),
                                         'in_sample_value_label_purity': purity,
                                         'interpretation': 'Descriptive only; high-cardinality purity is not held-out performance or causal evidence'})
    for column in ('User', 'Agent_name', 'host', 'Decoder_name', 'Activity', 'Action'):
        result['distributions'][column] = raw.groupby(['origin', column], dropna=False).size().rename('events').reset_index().fillna('<missing>').to_dict('records')
    result['temporal_hour'] = raw.assign(hour=raw.time.dt.hour).groupby(['origin', 'hour']).size().rename('events').reset_index().to_dict('records')
    result['temporal_day'] = raw.assign(day=raw.time.dt.strftime('%Y-%m-%d')).groupby(['origin', 'day']).size().rename('events').reset_index().to_dict('records')
    result['command_availability'] = {origin: {'present': int(group.Command.notna().sum()), 'missing': int(group.Command.isna().sum())} for origin, group in raw.groupby('origin')}
    result['command_top20_by_origin'] = {origin: group.Command.value_counts().head(20).to_dict() for origin, group in raw.groupby('origin')}
    result['source_controlled_attack_evaluation_available'] = all(len(v) == 2 for v in result['within_source_class_support'].values())
    result['identifiability'] = 'No marker-defined origin contains both labels. Coarser user/decoder/host mixtures are not proof of the same generation process.'
    return result


def _feature_audit(frame, names):
    records = []
    for name in names:
        a = frame.loc[frame.origin_cohort == 'simulation_only', name].to_numpy(float)
        b = frame.loc[frame.origin_cohort == 'non_simulation_only', name].to_numpy(float)
        records.append({'feature': name, 'classification': 'legitimate behavioral definition; potential indirect source proxy; causal discrimination unidentifiable',
                        'simulation': distribution(a), 'non_simulation': distribution(b),
                        'simulation_zero_fraction': float((a == 0).mean()) if len(a) else None,
                        'non_simulation_zero_fraction': float((b == 0).mean()) if len(b) else None})
    return records


def _split_audit(events, frame):
    items = {}
    for split, g in frame.groupby('split'):
        ids = {rid for values in g.record_ids for rid in values}
        e = events.loc[events.source_record_id.isin(ids)]
        items[split] = {'windows': len(g), 'positive': int(g.label.sum()), 'normal': int((~g.label).sum()),
                        'min_time': str(g.window_start.min()), 'max_time': str(g.window_start.max()),
                        'source_cohorts': g.origin_cohort.value_counts().to_dict(),
                        'users': sorted(g.user.unique()), 'events': ids,
                        'payloads': set(e.payload_hash), 'proxies': {v for values in g.scenario_proxies for v in values},
                        'feature_hashes': set(pd.util.hash_pandas_object(g[FEATURE_NAMES], index=False).astype(str))}
    pairs = []
    for i, a in enumerate(items):
        for b in list(items)[i + 1:]:
            pairs.append({'partitions': [a, b], **{kind + '_overlap': len(items[a][kind] & items[b][kind]) for kind in ('events', 'payloads', 'proxies', 'feature_hashes')},
                          'user_overlap': len(set(items[a]['users']) & set(items[b]['users']))})
    for item in items.values():
        for key in ('events', 'payloads', 'proxies', 'feature_hashes'):item[key] = len(item[key])
    return {'splits': items, 'overlap_pairs': pairs,
            'near_duplicate_limit': 'Exact payload and exact numerical duplicate purging verified; semantic near-duplicates/undocumented sessions cannot be certified independent.'}


def _false_negatives(frame, model, output):
    test = frame.loc[frame.split == 'test'].copy()
    missed = test.loc[test.label & (test.risk_score < model.threshold)].copy()
    missed['distance_below_high'] = model.threshold - missed.risk_score
    missed['attack_fraction'] = missed.attack_event_count / missed.event_count
    missed['near_threshold_within_5'] = missed.distance_below_high <= 5
    missed['low_volume_at_most_5'] = missed.event_count <= 5
    missed['familiar_hosts'] = missed.new_hosts == 0
    missed['component_above_ensemble_threshold'] = missed[['if_score', 'neural_score']].max(axis=1) >= model.threshold
    missed['within_one_prior_std'] = missed.volume_deviation.abs() <= 1
    missed['minority_attack_events_at_most_10pct'] = missed.attack_fraction <= .1
    flags = ['near_threshold_within_5', 'low_volume_at_most_5', 'familiar_hosts',
             'component_above_ensemble_threshold', 'within_one_prior_std', 'minority_attack_events_at_most_10pct']
    columns = ['window_id', 'user', 'window_start', 'origin_cohort', 'origin_fraction_non_simulation', 'risk_score',
               'if_score', 'neural_score', 'graph_score', 'event_count', 'volume_deviation',
               'new_hosts', 'new_resources', 'new_commands', 'attack_event_count', 'attack_fraction', 'distance_below_high', *flags]
    missed[columns].to_csv(output / 'false_negatives.csv', index=False)
    assert len(missed) == 99
    return {'missed_hours': len(missed), 'overlapping_diagnostic_groups': {name: int(missed[name].sum()) for name in flags},
            'score_distributions': {name: distribution(missed[name]) for name in ('risk_score', 'if_score', 'neural_score', 'graph_score', 'event_count', 'distance_below_high')},
            'origin_cohorts': missed.origin_cohort.value_counts().to_dict(), 'accounts': missed.user.value_counts().to_dict(),
            'warning': 'Overlapping observed patterns, not proven root causes. Component comparison at the ensemble cutoff is descriptive, not a calibrated alternative operating point.'}


def source_locations():
    wanted = {'src/data/spedia.py': ['load_spedia', 'prepare_events', 'aggregate_windows'],
              'src/models/behavioral.py': ['fit', 'train_spedia', 'choose_threshold'],
              'src/evaluation/spedia_experiment.py': ['fit', 'transform', 'run_experiment'],
              'src/inference/raw.py': ['parse_csv', 'generate_features'],
              'src/inference/service.py': ['import_csv']}
    result = []
    for path, names in wanted.items():
        for node in ast.walk(ast.parse(Path(path).read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
                result.append({'path': path, 'symbol': node.name, 'line': node.lineno})
    return result


def run_audit(output, source='logs_SPEDIA_annotated_en.csv', frozen=FROZEN):
    out = Path(output); frozen = Path(frozen)
    if (out / 'audit_metrics.json').exists():raise FileExistsError('Audit output already exists; choose a new version')
    if not (out / 'preservation_before.json').is_file():raise ValueError('Create preservation inventory before code changes')
    report = json.loads((frozen / 'metrics.json').read_text())
    if sha256_file(source) != report['dataset']['provenance']['sha256'] or sha256_file(frozen / 'scores.parquet') != report['scores_sha256']:
        raise ValueError('Original source/score identity mismatch')
    raw = load_spedia(source)
    native = list(pd.read_csv(source, nrows=0))
    events, preparation = prepare_events(raw)
    frame = pd.read_parquet(frozen / 'scores.parquet')
    features = pd.read_parquet('data/spedia/features-temporal/features.parquet')
    regenerated, _, purged = aggregate_windows(events)
    pd.testing.assert_frame_equal(regenerated.set_index('window_id')[FEATURE_NAMES].sort_index(), features.set_index('window_id')[FEATURE_NAMES].sort_index())
    frame = source_windows(raw, frame)
    model = load_verified_model(frozen / 'model.joblib', report['artifact_sha256'])
    state = joblib.hash(model)
    score, tiers, _ = model.score(frame[model.names])
    np.testing.assert_array_equal(score, frame.risk_score.to_numpy())
    np.testing.assert_array_equal(tiers, frame.risk_tier.to_numpy())
    assert state == joblib.hash(model)
    train = frame.loc[frame.split == 'train']; validation = frame.loc[frame.split == 'validation']; test = frame.loc[frame.split == 'test']
    origin_report, diagnostic = fit_origin_classifier(train, validation, FEATURE_NAMES)
    if diagnostic:joblib.dump(diagnostic, out / 'source_classifier_30.joblib', compress=3)
    v5 = pd.read_parquet('data/spedia/experiment-v5/development_features.parquet')
    v5names = json.loads(Path('data/spedia/experiment-v5/report.json').read_text())['features']['enhanced']
    v5 = v5.merge(frame[['window_id', 'origin_cohort', 'scenario_proxies']], on='window_id', validate='one_to_one')
    origin44, diagnostic44 = fit_origin_classifier(v5.loc[v5.split == 'train'], v5.loc[v5.split == 'validation'], v5names)
    if diagnostic44:joblib.dump(diagnostic44, out / 'source_classifier_v5_44.joblib', compress=3)
    user_root = Path('data/artifacts/spedia-4011d05769e043ffa773b033ccd41c3b')
    user_report = json.loads((user_root / 'metrics.json').read_text())
    user_model = load_verified_model(user_root / 'model.joblib', user_report['artifact_sha256'])
    user_data = pd.read_parquet(user_root / 'scores.parquet'); user_test = user_data.loc[user_data.split == 'test']
    normal_test = test.loc[~test.label]
    result = {'scope': 'Origin association and historical diagnostics; not causal correction or independent validation',
              'raw_origin': _raw_audit(raw, native), 'feature_audit_30': _feature_audit(frame, FEATURE_NAMES),
              'feature_audit_v5_44': _feature_audit(v5, v5names),
              'preparation': preparation, 'feature_vectors_reproduced': len(regenerated), 'duplicate_feature_windows_purged': purged,
              'split_audit': _split_audit(events, frame), 'source_prediction_30': origin_report, 'source_prediction_v5_44': origin44,
              'baseline': evaluate_known(test.label, test.risk_score, model.threshold),
              'normal_temporal_test': evaluate_known(normal_test.label, normal_test.risk_score, model.threshold),
              'normal_user_disjoint_test': evaluate_known(user_test.label, user_model.score(user_test)[0], user_model.threshold),
              'normal_test_scope': 'Historical previously examined normal cohorts; not independent organization data. User-disjoint model differs from temporal model.',
              'score_distributions_by_source': {cohort: {n: distribution(g[n]) for n in ('risk_score', 'if_score', 'neural_score', 'graph_score')} for cohort, g in frame.groupby('origin_cohort')},
              'false_negatives': _false_negatives(frame, model, out), 'source_locations': source_locations(),
              'external_evaluation': {'executed': False, 'reason': 'CERT sources exist but have different feature/telemetry contracts and unresolved parent-source overlap with SPEDIA; no independent compatible labeled source verified.'},
              'source_controlled_attack_evaluation': {'available': False, 'reason': 'Marker-defined origin perfectly determines event annotations; coarse decoder/account strata do not establish same generation process.'},
              'production_unchanged': True}
    write_json(out / 'audit_metrics.json', result)
    write_json(out / 'source_locations.json', result['source_locations'])
    print(json.dumps({'audit': str(out), 'source_prediction_30': origin_report.get('metrics'), 'false_negative_groups': result['false_negatives']['overlapping_diagnostic_groups']}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    run_audit(args.output)
