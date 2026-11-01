"""Versioned development-only experiments. Original held-out scores are never scored here."""
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import re
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import RobustScaler

from src.data.integrity import atomic_json, sha256_file
from src.data.spedia import FEATURE_NAMES, load_spedia
from src.models.behavioral import metrics

EXTRA = ['command_surprise_max', 'action_surprise_max', 'transition_surprise_max',
         'hour_surprise', 'max_events_5m', 'idle_sessions', 'short_session_fraction',
         'gap_max_seconds', 'gap_median_seconds', 'host_switch_rate',
         'new_user_host_action_fraction', 'cold_start', 'volume_drop', 'command_fraction']


def token(value):
    # No identifiers or payload strings enter the numerical matrix.
    if pd.isna(value): return '<absent>'
    return re.sub(r'\d+', '#', str(value).strip().lower().split(' ')[0])


class EventFeatures:
    """Training-normal vocabularies; relationship history updates after each closed hour.

    Session means an observed idle-gap segment, not a verified login session.
    No labels are consulted by transform; equal timestamps have stable ID ordering.
    """
    def fit(self, normal):
        self.commands = Counter(token(x) for x in normal.get('Command', pd.Series(dtype=str)).dropna())
        self.actions = Counter(normal.Activity.astype(str) + '|' + normal.Action.astype(str))
        self.hours = Counter(normal.time.dt.hour)
        self.transitions = Counter()
        for _, g in normal.sort_values(['time', 'source_record_id']).groupby('user'):
            a = (g.Activity.astype(str) + '|' + g.Action.astype(str)).tolist()
            self.transitions.update(zip(a, a[1:]))
        return self

    @staticmethod
    def surprise(counter, key):
        return -np.log((counter[key] + 1) / (sum(counter.values()) + len(counter) + 1))

    def transform(self, events):
        rows = []; seen = defaultdict(set); previous = {}; counts = defaultdict(list)
        for (start, user), g in events.sort_values(['time', 'source_record_id']).groupby(['window_start', 'user'], sort=True):
            g = g.sort_values(['time', 'source_record_id'])
            seconds = g.time.astype('int64').to_numpy() / 1e9
            gaps = np.diff(seconds); actions = (g.Activity.astype(str) + '|' + g.Action.astype(str)).tolist()
            pairs = list(zip(g.host.astype(str), actions)); hosts = g.host.astype(str).to_numpy()
            boundaries = np.r_[0, np.flatnonzero(gaps > 300) + 1, len(g)]
            lengths = np.diff(boundaries)
            spans = [seconds[b-1]-seconds[a] for a,b in zip(boundaries[:-1],boundaries[1:])]
            commands = g.get('Command', pd.Series(dtype=str)).dropna()
            transitions = list(zip([previous[user]] + actions[:-1], actions)) if user in previous else list(zip(actions, actions[1:]))
            # Rolling five-minute event maximum, available at hour closure.
            left = np.searchsorted(seconds, seconds - 300, side='left')
            prior = [n for t,n in counts[user] if start-pd.Timedelta(days=7) <= t < start]
            row = dict(user=user, window_start=str(start),
                command_surprise_max=max([self.surprise(self.commands, token(c)) for c in commands], default=0.),
                action_surprise_max=max(self.surprise(self.actions, a) for a in actions),
                transition_surprise_max=max([self.surprise(self.transitions, p) for p in transitions], default=0.),
                hour_surprise=self.surprise(self.hours, start.hour),
                max_events_5m=float(np.max(np.arange(len(g)) - left + 1)), idle_sessions=float(len(lengths)),
                short_session_fraction=float(np.mean(np.array(spans) <= 60)),
                gap_max_seconds=float(gaps.max()) if len(gaps) else 0.,
                gap_median_seconds=float(np.median(gaps)) if len(gaps) else 0.,
                host_switch_rate=float(np.mean(hosts[1:] != hosts[:-1])) if len(gaps) else 0.,
                new_user_host_action_fraction=sum(p not in seen[user] for p in pairs)/len(pairs),
                cold_start=float(not prior), volume_drop=max(0., (np.mean(prior)-len(g))/max(np.std(prior),1)) if prior else 0.,
                command_fraction=len(commands)/len(g))
            rows.append(row); seen[user].update(pairs); previous[user]=actions[-1]; counts[user].append((start,len(g)))
        return pd.DataFrame(rows)


def threshold(y, score):
    p,r,t = precision_recall_curve(y,score)
    f = 2*p[:-1]*r[:-1]/np.maximum(p[:-1]+r[:-1],1e-12)
    # Conservative tie-breaking, and no clipping of continuous scores.
    return float(t[np.flatnonzero(f == f.max())[-1]])


def signed_log(x):
    return np.sign(x)*np.log1p(np.abs(x))


def run_experiment(source, frozen, output, *, epochs=100):
    out=Path(output);out.mkdir(parents=True, exist_ok=False)
    frozen=Path(frozen); original=pd.read_parquet(frozen/'scores.parquet')
    development=original.loc[original.split.isin(['train','validation'])].copy()
    # Only membership metadata of the old test is used for an exclusion assertion.
    forbidden={rid for ids in original.loc[original.split=='test','record_ids'] for rid in ids}
    wanted={rid for ids in development.record_ids for rid in ids}
    assert wanted.isdisjoint(forbidden)
    checks={str(p):sha256_file(p) for p in frozen.iterdir() if p.is_file()}
    raw=load_spedia(source)
    events=raw.loc[raw.source_record_id.isin(wanted)].copy()
    events['window_start']=events.time.dt.floor('h')
    train_ids={rid for ids in development.loc[(development.split=='train') & ~development.label,'record_ids'] for rid in ids}
    encoder=EventFeatures().fit(events.loc[events.source_record_id.isin(train_ids)])
    additions=encoder.transform(events.drop(columns=['Anomaly']))
    frame=development.merge(additions,on=['user','window_start'],validate='one_to_one')
    assert len(frame)==len(development)
    atomic_json(out/'plan.json',dict(version=out.name,selection='Validation F1 threshold; anomaly family selected by validation AP then F1. Fixed seed 42. No original test scoring.',
        frozen_checksums=checks,source_sha256=sha256_file(source),
        training_window_ids=frame.loc[frame.split=='train','window_id'].tolist(),
        validation_window_ids=frame.loc[frame.split=='validation','window_id'].tolist(),
        final_test=dict(status='awaiting_independent_acquisition', records_reserved=0,
            requirements=['New exercise or prospective collection, independently generated from SPEDIA and CERT derivatives.',
                'Both attack and benign activity within each origin; verified participant/scenario grouping.',
                'Custodian seals raw SHA256 and labels before one-shot evaluation; reject all old IDs and duplicate payloads.',
                'Freeze this experiment before acquisition. No changes after final labels are opened.']),
        source_warning='Origin perfectly predicts event labels. Within-origin discrimination is unidentifiable; controls cannot establish malicious-intent detection.'))
    sets={'original_log_robust':FEATURE_NAMES,'enhanced':FEATURE_NAMES+EXTRA,
          'reduced_source_proxies':['event_count','prior_events_mean_7d','prior_events_std_7d','volume_deviation','hours_since_previous','active_span_seconds','interevent_std_seconds','max_events_5m','idle_sessions','short_session_fraction','gap_max_seconds','gap_median_seconds','cold_start','volume_drop']}
    results={}; models={}; diagnostics=[]
    train=frame.loc[frame.split=='train'];val=frame.loc[frame.split=='validation'];normal=train.loc[~train.label]
    for spec,names in sets.items():
        scaler=RobustScaler().fit(signed_log(normal[names].to_numpy(float)))
        x=scaler.transform(signed_log(normal[names].to_numpy(float)))
        xv=scaler.transform(signed_log(val[names].to_numpy(float)))
        xt=scaler.transform(signed_log(train[names].to_numpy(float)))
        estimators={'isolation_forest':IsolationForest(n_estimators=200,random_state=42,n_jobs=1),
            'pca':PCA(n_components=max(1,len(names)//2),random_state=42),
            'neural_autoencoder':MLPRegressor(hidden_layer_sizes=(24,8,24),alpha=.001,random_state=42,batch_size=64,shuffle=False),
            'supervised_logistic':LogisticRegression(C=1,class_weight='balanced',max_iter=2000,random_state=42)}
        results[spec]={}
        for name,model in estimators.items():
            started=time.perf_counter()
            if name=='supervised_logistic':model.fit(xt,train.label)
            elif name=='neural_autoencoder':
                best=float('inf');patience=0; chosen=None
                for _ in range(epochs):
                    model.partial_fit(x,x)
                    mse=float(np.mean((model.predict(xv[~val.label])-xv[~val.label])**2))
                    if mse<best-1e-6:best=mse;chosen=copy.deepcopy(model);patience=0
                    else:patience+=1
                    if patience>=8:break
                model=chosen
            else:model.fit(x)
            fit_seconds=time.perf_counter()-started;started=time.perf_counter()
            if name=='isolation_forest':s=-model.score_samples(xv)
            elif name=='supervised_logistic':s=model.predict_proba(xv)[:,1]
            else:
                restored=model.inverse_transform(model.transform(xv)) if name=='pca' else model.predict(xv)
                residual=(xv-restored)**2;s=residual.mean(axis=1)
            scoring_seconds=time.perf_counter()-started;t=threshold(val.label,s)
            m=metrics(val.label,s,t); low=val.event_count.to_numpy()<=5
            m.update(fit_seconds=fit_seconds,scoring_seconds=scoring_seconds,
                low_activity=metrics(val.label.to_numpy()[low],s[low],t),
                score_kind='raw probability, supervised research comparator' if name=='supervised_logistic' else 'raw anomaly score, unbounded; not probability')
            results[spec][name]=m;models[(spec,name)]=dict(model=model,scaler=scaler,features=names,threshold=t)
            for i,row in enumerate(val.itertuples()):
                d=dict(spec=spec,model=name,window_id=row.window_id,label=bool(row.label),score=float(s[i]),prediction=bool(s[i]>=t),events=int(row.event_count))
                if name in ['pca','neural_autoencoder']:
                    d['largest_reconstruction_residuals']=[names[j] for j in np.argsort(-residual[i])[:3]]
                diagnostics.append(d)
    eligible=[(spec,name) for spec in sets for name in results[spec] if name!='supervised_logistic']
    selected=max(eligible,key=lambda k:(results[k[0]][k[1]]['pr_auc_average_precision'],results[k[0]][k[1]]['f1']))
    joblib.dump(dict(encoder=encoder,candidates=models,selected=selected),out/'experiment.joblib')
    frame.to_parquet(out/'development_features.parquet',index=False)
    pd.DataFrame(diagnostics).to_parquet(out/'validation_diagnostics.parquet',index=False)
    # Source controls are development-only; origin is never passed to a model.
    origin=pd.crosstab(events.simulation_marker,events.Anomaly).to_dict()
    frozen_val=development.loc[development.split=='validation']
    frozen_report=json.loads((frozen/'metrics.json').read_text())
    frozen_metrics=metrics(frozen_val.label,frozen_val.risk_score,frozen_report['calibration']['high_threshold'])
    report=dict(scope='Development validation only; repeated model selection is optimistic. No independent final result.',
        results=results,selected=selected,frozen_validation=frozen_metrics,origin_label_counts=origin,
        features=sets,final_test_status='Not acquired or reserved; requires an independent custodian/collection.',
        limitations=['Idle-gap segments are session proxies; no verified sessions or attack onset.',
            'Event-level indicators are max pooled into closed hours; no event-level detection or early-warning claim.',
            'No communication endpoints support a real network graph; host-action relationships are observed-context novelty.',
            'Source-reduced ablation still carries origin information. No within-origin class controls exist.',
            'History includes prior observed development hours only. Removed/purged records and inactive hours are not imputed.'])
    atomic_json(out/'report.json',report)
    assert all(sha256_file(p)==digest for p,digest in checks.items())
    return report
