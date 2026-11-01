"""Post-hoc diagnostics, validation-only operating points and genuine held-out replay.

Never calls fit; never writes to the original artifact or feature directories.
The replay sample is selected for explanation, not an unbiased evaluation sample.
"""
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from src.data.integrity import atomic_json, sha256_file, utcnow
from src.data.spedia import load_spedia, prepare_events
from src.models.behavioral import metrics


def operating_points(y, score):
    """Predeclared validation objectives, no test arguments accepted."""
    score=np.asarray(score);y=np.asarray(y,dtype=bool)
    candidates=[metrics(y,score,t) for t in np.unique(np.r_[0.,score,100.000001])]
    def choose(beta, floor=None):
        eligible=[m for m in candidates if m['recall'] is not None and (floor is None or m['precision']>=floor) and m['alert_count']]
        if not eligible:return None
        def key(m):
            p,r=m['precision'],m['recall'];f=(1+beta**2)*p*r/(beta**2*p+r) if p+r else 0.
            return (f,m['threshold'])
        return max(eligible,key=key)
    return {'precision_focused':choose(.5,.9),'balanced':choose(1.),'recall_focused':choose(2.)}


def block_intervals(frame, score, threshold, repetitions=1000, seed=42):
    """Resample whole calendar days, preserving all users/hours within each day."""
    rng=np.random.default_rng(seed);blocks=frame.window_start.str[:10].to_numpy();days=np.unique(blocks)
    values={k:[] for k in ('precision','recall','pr_auc_average_precision','false_alerts_per_1000_windows')}
    for _ in range(repetitions):
        ix=np.concatenate([np.flatnonzero(blocks==d) for d in rng.choice(days,len(days),replace=True)])
        m=metrics(frame.label.to_numpy()[ix],np.asarray(score)[ix],threshold)
        for k in values:
            if m[k] is not None:values[k].append(m[k])
    return {'method':'calendar-day cluster percentile bootstrap; descriptive, only five test days, not robust population coverage',
            'seed':seed,'resamples':repetitions,'clusters':len(days),
            'intervals_95':{k:[float(x) for x in np.quantile(v,[.025,.975])] if v else None for k,v in values.items()}}


def review(run,features,source,output):
    run,features,source,output=map(Path,(run,features,source,output))
    if output.exists():raise FileExistsError('Review outputs are immutable; choose a new directory')
    report=json.loads((run/'metrics.json').read_text());definition=json.loads(features.with_suffix('.json').read_text())
    checks={str(run/'model.joblib'):report['artifact_sha256'],str(run/'scores.parquet'):report['scores_sha256'],
            str(features):definition['features_sha256'],str(source):definition['provenance']['sha256']}
    for file,digest in checks.items():
        if sha256_file(file)!=digest:raise ValueError('Input digest mismatch: '+file)
    for file in (run/'metrics.json',run/'split_manifest.json',features.with_suffix('.json'),Path(definition['split_manifest_path'])):
        checks[str(file)]=sha256_file(file)
    model=joblib.load(run/'model.joblib');fingerprint=joblib.hash(model)
    table=pd.read_parquet(features);validation=table.loc[table.split=='validation'].copy();test=table.loc[table.split=='test'].copy()
    val_score=model.score(validation)[0]
    points=operating_points(validation.label,val_score) # Selection is finished before test scoring.
    thresholds={k:v['threshold'] if v else None for k,v in points.items()}
    output.mkdir(parents=True)
    atomic_json(output/'validation_operating_points.json',{'policy':'F0.5 with precision>=0.90, F1, F2; highest threshold breaks ties; no test labels used', 'thresholds':thresholds,'validation':points})
    test_score=model.score(test)[0];pred=test_score>=model.threshold
    frozen=metrics(test.label,test_score,model.threshold)
    evaluated={k:metrics(test.label,test_score,t) if t is not None else None for k,t in thresholds.items()}
    diagnostics=test.copy();diagnostics['score']=test_score;diagnostics['detected']=pred
    diagnostics['outcome']=np.where(test.label,np.where(pred,'TP','FN'),np.where(pred,'FP','TN'))
    per_user=[]
    for user,g in diagnostics.groupby('user'):
        per_user.append({'user':user,**metrics(g.label,g.score,model.threshold),'attack_events_in_flagged_hours':int(g.loc[g.detected,'attack_event_count'].sum()),'attack_events_total':int(g.attack_event_count.sum())})
    distributions={str(k):{'windows':len(g),'score_quantiles':g.score.quantile([0,.25,.5,.75,1]).to_dict(),
        'feature_medians':g[model.names].median().to_dict()} for k,g in diagnostics.groupby('outcome')}
    validation_associations=[]
    for name in model.names:
        values=validation[name].to_numpy()
        validation_associations.append({'feature':name,'ap_increasing':float(average_precision_score(validation.label,values)),
            'ap_decreasing':float(average_precision_score(validation.label,-values)),
            'normal_median':float(validation.loc[~validation.label,name].median()),'attack_median':float(validation.loc[validation.label,name].median())})
    coefficients=[]
    if model.supervised is not None:
        coefficients=sorted([{'feature':n,'standardized_log_odds':float(c)} for n,c in zip(model.names,model.supervised.coef_[0])],key=lambda x:-abs(x['standardized_log_odds']))
    raw=load_spedia(source);events,audit=prepare_events(raw)
    mapping={rid:r.outcome for r in diagnostics.itertuples() for rid in r.record_ids}
    represented=events.loc[events.source_record_id.isin(mapping)].copy();represented['outcome']=represented.source_record_id.map(mapping)
    source_tables=represented.groupby(['outcome','cert_tag','simulation_marker']).size().rename('events').reset_index().to_dict('records')
    proxies={s:set(g.scenario_proxy.dropna()) for s,g in events.groupby('split')}
    # Additional frozen subgroup: known proxy-containing hours vs all other test hours.
    # This is conditional reporting, not a new tuned split or independent experiment.
    proxy_ids=set(events.loc[events.scenario_proxy.notna(),'source_record_id'])
    has_proxy=test.record_ids.map(lambda ids:bool(set(ids)&proxy_ids)).to_numpy()
    subgroup={name:metrics(test.label.to_numpy()[mask],test_score[mask],model.threshold) if mask.any() else None
              for name,mask in [('known_scenario_proxy_hours',has_proxy),('unmarked_hours',~has_proxy)]}
    summary={'created_at':utcnow(),'model_version':report['version'],'input_checksums':checks,'frozen_model_hash':fingerprint,
        'test_reuse':'Post-hoc descriptive analysis of an already evaluated test set, not a fresh unbiased experiment. No model, weight or primary threshold changes.',
        'splits':{s:{'windows':len(g),'positive':int(g.label.sum()),'negative':int((~g.label).sum()),'prevalence':float(g.label.mean()),'random_ranking_pr_ap_baseline':float(g.label.mean())} for s,g in table.groupby('split')},
        'original_operating_point':frozen,'original_model_comparison':report['held_out_metrics'],'validation_feature_associations':validation_associations,'validation_selected_operating_points':evaluated,
        'confidence':block_intervals(test,test_score,model.threshold),'outcome_distributions':distributions,'per_user':per_user,
        'attack_event_coverage':{'total_attack_events':int(test.attack_event_count.sum()),'attack_events_in_flagged_hours':int(test.loc[pred,'attack_event_count'].sum()),'meaning':'Retrospective hour coverage, not event-level predictions or early detection'},
        'logistic_coefficients':coefficients,'source_outcome_cross_tab':source_tables,
        'predictor_audit':{'ordered_features':model.names,'direct_identifiers_annotations_scenario_proxies_in_matrix':False,
           'warning':'Absence of forbidden columns does not remove indirect source confounding. Labels perfectly follow simulation-marker origin; behavior counts and missing telemetry may encode origin. Coefficients are associations, not causal effects.'},
        'scenario_analysis':{'proxy_groups_per_split':{s:len(v) for s,v in proxies.items()},'train_test_proxy_overlap':len(proxies['train']&proxies['test']),
           'frozen_test_subgroups':subgroup,'limitation':'Known suffix groups were already purged across splits. Unmarked events lack scenario identity. Proxy-containing hours can mix unmarked records; not a verified participant-disjoint benchmark.',
           'additional_study_design':'Acquire participant/scenario and origin ground truth. Group complete user-hours and their scenario/participant links into connected components; hold whole components out, fit baselines on earlier training context only, select on disjoint validation components. Verify both classes in every split before training. Never move original test records into training. Existing hashed proxies alone cannot establish participant identity.'},
        'limitations':['Only five held-out days; bootstrap intervals are unstable and do not establish enterprise generalization.',
           'Window label is any attack event; low-count malicious windows can resemble routine activity.',
           'Source-normal validation calibration saturates components and suppresses amplitude differences above the reference maximum.',
           'Graph novelty can be zero for attacks on familiar hosts; this signal is not a communication graph.',
           'No independently sourced external evaluation or verified participant IDs are available.']}
    # Balanced qualitative replay: full retained user-hours, not individual chopped events.
    selected=[];total=0
    for outcome in ('TN','TP','FN','FP'):
        pool=diagnostics.loc[(diagnostics.outcome==outcome)&(diagnostics.event_count<=70)].sort_values(['window_start','user'])
        for row in pool.itertuples():
            if total+row.event_count>260:continue
            selected.append(row.window_id);total+=int(row.event_count)
            if sum(diagnostics.loc[diagnostics.window_id.isin(selected)&(diagnostics.outcome==outcome),'event_count'])>=40:break
    chosen=diagnostics.loc[diagnostics.window_id.isin(selected)].sort_values(['window_start','user']).copy()
    if not 100<=chosen.event_count.sum()<=300:raise ValueError('Replay sample size outside 100–300; review deterministic selection policy')
    selected_ids={x for ids in chosen.record_ids for x in ids}
    # All ground truth is kept out of the feature matrix and source-event replay file.
    replay_inputs=chosen[['window_id','user','window_start','window_index','record_ids',*model.names]].copy()
    replay_inputs.to_parquet(output/'replay_inputs.parquet',index=False)
    safe=['source_record_id','user','time','Activity','Action','host']
    events.loc[events.source_record_id.isin(selected_ids),safe].to_parquet(output/'replay_events.parquet',index=False)
    atomic_json(output/'replay_ground_truth.json',{'windows':[{'window_id':r.window_id,'label':bool(r.label),'example_outcome':r.outcome} for r in chosen.itertuples()],
          'events':raw.loc[raw.source_record_id.isin(selected_ids),['source_record_id','Anomaly']].to_dict('records')})
    manifest={'model_version':report['version'],'model_directory':str(run.resolve()),'inputs_sha256':sha256_file(output/'replay_inputs.parquet'),
        'events_sha256':sha256_file(output/'replay_events.parquet'),'ground_truth_sha256':sha256_file(output/'replay_ground_truth.json'),
        'source_sha256':sha256_file(source),'events':len(selected_ids),'windows':len(chosen),'selection':'Qualitative, outcome-selected held-out test examples; never use this selected sample to estimate performance.',
        'history':'Exact causal feature vectors from immutable original pipeline, including past-only seven-day history. Replay is frozen-feature inference, not history reconstructed from these selected events.',
        'feature_source':str(features.resolve()),'feature_source_sha256':sha256_file(features),'window_ids':chosen.window_id.tolist()}
    atomic_json(output/'replay_manifest.json',manifest)
    diagnostics[['window_id','user','window_start','label','score','outcome','event_count',*['command_events','session_events','http_events','file_events','email_events','device_events']]].to_parquet(output/'window_diagnostics.parquet',index=False)
    atomic_json(output/'missed_attack_examples.json',json.loads(diagnostics.loc[diagnostics.outcome=='FN',['window_id','user','window_start','score','event_count','record_ids']].head(20).to_json(orient='records')))
    if joblib.hash(model)!=fingerprint:raise AssertionError('Review mutated frozen model')
    atomic_json(output/'review.json',summary)
    _report(output,summary,manifest)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots()
    for label,g in diagnostics.groupby('label'):ax.hist(g.score,bins=np.arange(0,105,5),alpha=.5,label='Attack annotation' if label else 'Non-attack annotation')
    ax.axvline(model.threshold,color='black',linestyle='--',label='Original threshold');ax.set(xlabel='Frozen anomaly index',ylabel='Test user-hours');ax.legend();fig.tight_layout();fig.savefig(output/'score_distributions.png');plt.close(fig)
    return summary


def _report(output,sample,manifest):
    text='# Frozen SPEDIA detection review\n\nModel: `'+sample['model_version']+'`. '+sample['test_reuse']+'\n\n'
    text+='| Split | Positive hours | Negative hours | Prevalence / random-ranking PR-AP |\n|---|---:|---:|---:|\n'
    for n,m in sample['splits'].items():text+=f"| {n} | {m['positive']} | {m['negative']} | {m['prevalence']:.4f} |\n"
    text+='\nThresholds below were selected using validation F0.5 (precision ≥0.90), F1 and F2 respectively. Test results are descriptive applications of those fixed policies. None replaces the original deployed policy.\n\n| Policy | Threshold | Precision | Recall | F1 | TN / FP / FN / TP | Alerts/1000 | False alerts/1000 |\n|---|---:|---:|---:|---:|---|---:|---:|\n'
    for n,m in {'original':sample['original_operating_point'],**sample['validation_selected_operating_points']}.items():
        if m:text+=f"| {n} | {m['threshold']:.4f} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {sum(m['confusion_matrix'],[])} | {m['alerts_per_1000_windows']:.2f} | {m['false_alerts_per_1000_windows']:.2f} |\n"
    text+='\n## Complete frozen model comparison\n\nThese are the original saved test metrics. Supervised logistic uses labelled training data; anomaly models fit designated non-attack training windows.\n\n| Model | Precision | Recall | F1 | PR-AP | TN / FP / FN / TP | False alerts/1000 |\n|---|---:|---:|---:|---:|---|---:|\n'
    for n,m in sample['original_model_comparison'].items():
        text+=f"| {n} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['pr_auc_average_precision']:.4f} | {sum(m['confusion_matrix'],[])} | {m['false_alerts_per_1000_windows']:.2f} |\n"
    text+='\n## Why recall is limited\n\nThe original threshold misses 99 attack-labelled hours. Counts, category mix and causal history measure unusual behavior; they cannot reliably distinguish malicious intent in ordinary-looking commands or sessions. An any-attack hour label treats a single malicious event as a positive hour. A familiar host yields zero novelty, and percentile normalization compresses extreme activity. End-of-hour coverage is retrospective.\n\n'
    text+='Median events per hour by outcome: '+', '.join(f"{n}={v['feature_medians']['event_count']:.1f}" for n,v in sample['outcome_distributions'].items())+'. See `window_diagnostics.parquet` and `missed_attack_examples.json` for actual windows.\n\n'
    text+='Attack-event hour coverage (not event-level recall): '+json.dumps(sample['attack_event_coverage'])+'.\n\n'
    text+='## Supervised comparison and leakage audit\n\nThe supervised model learns which behavior directions correlate with known labels. Anomaly models instead learn departures from designated normal windows, including benign departures, and can miss common-looking attacks. No username, raw host, source flag, scenario ID, annotation text or target is in the numerical predictor contract. This does not prove absence of leakage: source origin perfectly predicts labels in the raw file, and activity mix, telemetry availability and sizes can carry indirect source shortcuts. Logistic PR-AP 0.941 therefore demonstrates research-dataset discrimination, not validated malicious-intent detection. The JSON includes standardized coefficients and origin/outcome cross-tabs; these are associations. No causal claim or independent generalization is supported.\n\nTop standardized coefficients:\n\n'
    for c in sample['logistic_coefficients'][:10]:text+=f"- {c['feature']}: {c['standardized_log_odds']:.4f}\n"
    text+='\n## Uncertainty and generalization\n\n'+sample['confidence']['method']+'. Intervals: `'+json.dumps(sample['confidence']['intervals_95'])+'`.\n\nThe existing user-disjoint study has zero positive windows in every partition after scenario purging. Attack recall and AP are undefined; it measures only false-alert behavior. Do not change its seed to find a flattering result.\n\n'+sample['scenario_analysis']['limitation']+'\n\nAdditional study design: '+sample['scenario_analysis']['additional_study_design']+'\n\n'
    text+='## Replay demonstration\n\n'+str(manifest['events'])+' genuine held-out events in '+str(manifest['windows'])+' complete retained user-hours. '+manifest['selection']+' '+manifest['history']+' Labels are in a separate ground-truth file and never passed to inference. Raw source remains unchanged.\n\n'
    text+='## Confirmed limitations and future work\n\n'+'\n'.join('- '+x for x in sample['limitations'])+'\n\nFuture experiments need verified scenario/origin metadata, representative benign telemetry and a new untouched external test set. Behavioral sequence models or alternate calibration would require new validation experiments; they are not claims of improvement on this frozen test.\n'
    (output/'REPORT.md').write_text(text)
