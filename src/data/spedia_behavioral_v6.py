"""Versioned causal SPEDIA behavior features; original spedia-hour-v1 is preserved.

The same label-free transformation serves offline research and context-based
inference. A behavioral definition does not prove freedom from source proxies.
"""
from __future__ import annotations
from collections import Counter
import re
import numpy as np
import pandas as pd

from src.data.spedia import ACTIVITIES, FEATURE_NAMES, aggregate_windows

VERSION = 'spedia-behavioral-v6'
EXTRA = ['peak_5m_fraction', 'peak_15m_fraction', 'file_peak_5m_fraction',
         'failed_login_fraction', *[a + '_fraction_change_7d' for a in ACTIVITIES],
         'activity_mix_l1_change_7d', 'personal_volume_mad_z_7d',
         'personal_volume_ratio_7d', 'volume_change_previous', 'host_switch_fraction',
         'transition_novelty_fraction', 'resource_novelty_fraction',
         'command_novelty_fraction', 'host_novelty_fraction', 'unusual_personal_hour',
         'idle_gap_segments', 'short_segment_fraction', 'gap_max_seconds',
         'gap_median_seconds', 'cold_start']
NAMES = [*FEATURE_NAMES, *EXTRA]
PERSONAL = [n for n in EXTRA if n not in ('idle_gap_segments', 'gap_max_seconds', 'gap_median_seconds')]
DEFINITIONS = {
    'peak_5m_fraction': 'Maximum count in trailing inclusive 300-second intervals ending at observed events / hourly event count.',
    'peak_15m_fraction': 'Maximum count in trailing inclusive 900-second intervals ending at observed events / hourly event count.',
    'file_peak_5m_fraction': 'Maximum file-event count in trailing inclusive 300-second intervals / max(hourly file count,1).',
    'failed_login_fraction': 'Login Failed or Multiple failed logins events / hourly event count.',
    'activity_mix_l1_change_7d': 'L1 distance between current activity fractions and mean earlier observed-hour fractions in [t-168h,t), else zero.',
    'personal_volume_mad_z_7d': '(Current count - prior observed-hour median) / max(1.4826 * prior MAD,1), else zero.',
    'personal_volume_ratio_7d': 'Current count / max(prior observed-hour median,1), else zero.',
    'volume_change_previous': '(Current count - previous observed-hour count) / max(previous count,1), else zero.',
    'host_switch_fraction': 'Fraction of consecutive current-hour events whose normalized agent host changes; not network traffic.',
    'transition_novelty_fraction': 'Fraction of action/normalized-command transitions absent in all earlier user history. Current hour updates occur afterward.',
    'resource_novelty_fraction': 'Current Path/Filename union strings absent in earlier history / max(current resource count,1).',
    'command_novelty_fraction': 'Current full command strings absent in earlier history / max(current distinct command count,1).',
    'host_novelty_fraction': 'Current hosts absent in earlier history / max(current distinct host count,1).',
    'unusual_personal_hour': '-log((earlier user observations in this clock hour+1)/(all earlier user observations+24)); first observation zero.',
    'idle_gap_segments': 'Number of within-hour observed event segments separated by gaps >300 seconds; not verified sessions.',
    'short_segment_fraction': 'Fraction of these segments spanning <=60 seconds.',
    'gap_max_seconds': 'Maximum current-hour adjacent event gap, else zero.',
    'gap_median_seconds': 'Median current-hour adjacent event gap, else zero.',
    'cold_start': 'One when no earlier user-hour exists in [t-168h,t), else zero.',
}
for activity in ACTIVITIES:
    DEFINITIONS[activity + '_fraction_change_7d'] = f'Current {activity} event fraction minus mean earlier observed-hour fraction in [t-168h,t), else zero.'


def contract():
    return {'version': VERSION, 'production_compatible': False, 'scoring_time': 'Completed hour only',
            'names': NAMES, 'dtype': 'float64', 'additional_features': DEFINITIONS,
            'base_contract': 'spedia-hour-v1', 'novelty': 'Cumulative earlier user history; no raw identifiers in numerical vectors',
            'limitations': ['All features may still carry source-generation information.',
                           'Source wall-clock times have no supplied timezone.',
                           'Observed-hour histories do not impute inactive hours.']}


def _peak(seconds, width):
    if not len(seconds):return 0
    return int(np.max(np.arange(len(seconds)) - np.searchsorted(seconds, seconds - width, side='left') + 1))


def _action(row):
    command = getattr(row, 'Command', None)
    token = '' if pd.isna(command) or not str(command).strip() else re.sub(r'\d+', '#', str(command).strip().lower().split()[0])
    return str(row.Activity) + '|' + str(row.Action) + ('|' + token if row.Activity == 'command' else '')


class CausalBehaviorFeatures:
    """Pure context replay; never fits dictionaries or reads labels/source markers."""
    def transform(self, events):
        required = {'user', 'time', 'host', 'Activity', 'Action', 'source_record_id'}
        if not required <= set(events):raise ValueError('Missing normalized event context')
        e = events.copy()
        if e.source_record_id.duplicated().any():raise ValueError('Duplicate source event IDs')
        e['time'] = pd.to_datetime(e.time)
        if e.time.isna().any() or e.user.isna().any() or e.host.isna().any():raise ValueError('Invalid user/time/host context')
        if e.time.dt.tz is not None:raise ValueError('Use source wall-clock timestamps without timezone')
        e['window_start'] = e.time.dt.floor('h')
        records = []
        for user, account in e.groupby('user', sort=True):
            history = []; seen = {k: set() for k in ('resources', 'commands', 'hosts', 'transitions')}
            hours = Counter(); previous_count = None; previous_action = None
            for start, g in account.sort_values(['time', 'source_record_id']).groupby('window_start', sort=True):
                g = g.sort_values(['time', 'source_record_id'])
                seconds = g.time.astype('int64').to_numpy() / 1e9
                gaps = np.diff(seconds); count = len(g)
                past = [r for r in history if start - pd.Timedelta(hours=168) <= r[0] < start]
                counts = np.asarray([r[1] for r in past], float)
                fractions = np.array([g.Activity.eq(a).sum() / count for a in ACTIVITIES])
                prior_mix = np.mean([r[2] for r in past], axis=0) if past else fractions
                med = float(np.median(counts)) if past else 0.
                mad = float(np.median(np.abs(counts - med))) if past else 0.
                def values(column):return set(g[column].dropna().astype(str)) if column in g else set()
                current = {'resources': values('Path') | values('Filename'), 'commands': values('Command'), 'hosts': values('host')}
                actions = [_action(r) for r in g.itertuples()]
                transitions = list(zip([previous_action] + actions[:-1], actions)) if previous_action is not None else list(zip(actions, actions[1:]))
                boundaries = np.r_[0, np.flatnonzero(gaps > 300) + 1, count]
                spans = [seconds[b - 1] - seconds[a] for a, b in zip(boundaries[:-1], boundaries[1:])]
                file_seconds = seconds[g.Activity.eq('file').to_numpy()]
                hosts = g.host.astype(str).to_numpy()
                r = {'user': user, 'window_start': str(start),
                     'peak_5m_fraction': _peak(seconds, 300) / count,
                     'peak_15m_fraction': _peak(seconds, 900) / count,
                     'file_peak_5m_fraction': _peak(file_seconds, 300) / max(len(file_seconds), 1),
                     'failed_login_fraction': float(g.Action.isin(['Login Failed', 'Multiple failed logins']).sum() / count),
                     **{a + '_fraction_change_7d': float(fractions[i] - prior_mix[i]) for i, a in enumerate(ACTIVITIES)},
                     'activity_mix_l1_change_7d': float(np.abs(fractions - prior_mix).sum()),
                     'personal_volume_mad_z_7d': (count - med) / max(1.4826 * mad, 1.) if past else 0.,
                     'personal_volume_ratio_7d': count / max(med, 1.) if past else 0.,
                     'volume_change_previous': (count - previous_count) / max(previous_count, 1) if previous_count is not None else 0.,
                     'host_switch_fraction': float(np.mean(hosts[1:] != hosts[:-1])) if count > 1 else 0.,
                     'transition_novelty_fraction': sum(t not in seen['transitions'] for t in transitions) / max(len(transitions), 1),
                     **{name: len(current[k] - seen[k]) / max(len(current[k]), 1) for k, name in
                        [('resources', 'resource_novelty_fraction'), ('commands', 'command_novelty_fraction'), ('hosts', 'host_novelty_fraction')]},
                     'unusual_personal_hour': float(-np.log((hours[start.hour] + 1) / (sum(hours.values()) + 24))) if history else 0.,
                     'idle_gap_segments': float(len(spans)), 'short_segment_fraction': float(np.mean(np.asarray(spans) <= 60)),
                     'gap_max_seconds': float(gaps.max()) if len(gaps) else 0.,
                     'gap_median_seconds': float(np.median(gaps)) if len(gaps) else 0., 'cold_start': float(not past)}
                records.append(r)
                for key in current:seen[key].update(current[key])
                seen['transitions'].update(transitions); hours[start.hour] += 1
                history.append((start, count, fractions)); previous_count = count; previous_action = actions[-1]
        result = pd.DataFrame(records, columns=['user', 'window_start', *EXTRA])
        if not result.empty:
            result[EXTRA] = result[EXTRA].astype('float64')
            if not np.isfinite(result[EXTRA].to_numpy()).all():raise ValueError('Nonfinite behavioral features')
        return result


def features_for_windows(events, windows):
    """Join additional causal features to already verified base features by user/hour."""
    extra = CausalBehaviorFeatures().transform(events)
    base = windows.copy(); base['window_start'] = base.window_start.astype(str)
    result = base.merge(extra, on=['user', 'window_start'], validate='one_to_one', how='left')
    if result[NAMES].isna().any().any():raise ValueError('Missing causal behavior features')
    return result


def inference_features(context, new_events, time_origin):
    """Shared V6 offline/inference transformation; native context guards remain mandatory."""
    from src.inference.raw import generate_features
    base = generate_features(context, new_events, time_origin)
    relevant = context.loc[context.user.isin(new_events.user.unique())]
    return features_for_windows(pd.concat([relevant, new_events], ignore_index=True), base)
