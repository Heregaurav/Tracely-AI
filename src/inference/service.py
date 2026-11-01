"""Transactional inference stream; never writes benchmark/evaluation tables."""
import hashlib
import json
from pathlib import Path
import joblib
import pandas as pd
from sqlalchemy import select,text
from src.data.neon_assets import resolve_asset_path
from src.data.spedia import FEATURE_NAMES
from src.db.models import InferenceRun,InferenceAlert,ModelVersion,AuditLog
from .artifacts import load_verified_model
from .raw import (InputError,load_context,parse_csv,timestamp,generate_features,canonical_records,from_records)


def active(db,dataset_id):
    row=db.scalar(select(ModelVersion).where(ModelVersion.dataset_id==dataset_id,ModelVersion.active))
    if row is None or row.feature_version!='spedia-hour-v1':raise InputError('An active compatible frozen SPEDIA model must be published first.')
    return row


def stream(db,model,manifest,base):
    if model.report['dataset']['provenance']['sha256']!=manifest['source_sha256'] or model.report['dataset']['features_sha256']!=manifest['features_sha256']:raise InputError('Historical snapshot does not match this frozen model source/features.')
    runs=list(db.scalars(select(InferenceRun).where(InferenceRun.model_version==model.id).order_by(InferenceRun.created_at,InferenceRun.id)))
    token=manifest['events_sha256'];boundary=manifest['next_coverage_start'];head=None;frames=[base]
    children={r.context_token:r for r in runs}
    if len(children)!=len(runs):raise InputError('Historical inference stream has a conflicting branch.')
    visited=set()
    while token in children:
        run=children[token]
        if run.id in visited or run.parent_id!=head or timestamp(run.coverage_start)!=timestamp(boundary):raise InputError('Historical inference chain is inconsistent; repair context before uploading.')
        visited.add(run.id)
        frames.append(from_records(run.events));token=run.id;head=run.id;boundary=run.coverage_end
    if len(visited)!=len(runs):raise InputError('Historical inference chain has an orphaned run.')
    return pd.concat(frames,ignore_index=True),token,boundary,head


def context_info(factory,directory,dataset_id):
    manifest,base=load_context(directory)
    with factory() as db:
        model=active(db,dataset_id);context,token,boundary,_=stream(db,model,manifest,base)
        return {'context_token':token,'next_coverage_start':boundary,'model_version':model.id,'threshold':model.report['calibration']['high_threshold'],
            'known_users':sorted(context.user.unique().tolist()),'source_policy':manifest['source_policy'],
            'scope':'New imported predictions; not benchmark evaluation or independent validation.'}


def import_csv(factory,directory,dataset_id,content,settings,*,actor,allow_fixture=False):
    required={'context_token','coverage_start','coverage_end','complete_hours','profile','source_kind','provenance'}
    if set(settings)!=required:raise InputError('Supply context_token, coverage_start, coverage_end, complete_hours, profile, source_kind and provenance.')
    if settings['complete_hours']!='true':raise InputError('Confirm complete observed telemetry for all users in this registered stream over the declared closed hours; partial hours cannot be scored.')
    if settings['profile']!='spedia-v2-native':raise InputError('Only semantically compatible SPEDIA v2 activity/action values and native numeric units are supported.')
    if settings['source_kind'] not in ('user-supplied-unverified','engineering-test-fixture'):raise InputError('Unsupported source_kind; imported CSV is not automatically an independent benchmark.')
    if settings['source_kind']=='engineering-test-fixture' and not allow_fixture:raise InputError('Engineering fixtures are disabled in this deployment.')
    description=settings['provenance']
    if not isinstance(description,str) or not 10<=len(description)<=1000:raise InputError('Describe the actual source, collection scope and telemetry compatibility in 10–1000 characters.')
    start,end=timestamp(settings['coverage_start']),timestamp(settings['coverage_end'])
    if start!=start.floor('h') or end!=end.floor('h') or not pd.Timedelta(0)<end-start<=pd.Timedelta(hours=24):raise InputError('Coverage must contain 1–24 complete aligned hours, with end exclusive.')
    new=parse_csv(content,start,end)
    manifest,base=load_context(directory)
    payload_sha=hashlib.sha256(content).hexdigest()
    with factory.begin() as db:
        db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':'raw-inference:'+dataset_id})
        row=active(db,dataset_id)
        key=json.dumps({'input_sha256':payload_sha,'settings':settings,'model':row.id},sort_keys=True,separators=(',',':'))
        run_id=hashlib.sha256(key.encode()).hexdigest()
        previous=db.get(InferenceRun,run_id)
        if previous:return {'run_id':run_id,'reused':True}
        context,token,boundary,parent=stream(db,row,manifest,base)
        if settings['context_token']!=token:raise InputError('Historical context changed; refresh context before uploading. No stale-context predictions were saved.')
        if start!=timestamp(boundary):raise InputError(f'Coverage must start at {boundary}; a gap or overlap would make history incomplete.')
        artifact=resolve_asset_path(row.artifact_path)/'model.joblib'
        model=load_verified_model(artifact,row.artifact_sha256,error_type=InputError)
        if model.names!=FEATURE_NAMES:raise InputError('Saved feature order differs from the supported inference contract.')
        features=generate_features(context,new,manifest['time_origin'])
        before=joblib.hash(model);score,tiers,components=model.score(features[model.names])
        if joblib.hash(model)!=before:raise InputError('Frozen model changed during inference.')
        predictions=[];alerts=[]
        for i,r in enumerate(features.itertuples()):
            flagged=bool(score[i]>=model.threshold)
            alert_id=hashlib.sha256((run_id+'|'+r.window_id).encode()).hexdigest() if flagged else None
            explanation={'kind':'Observed behavior comparisons, not exact attribution or proof of intent','event_count':float(r.event_count),
                'prior_7d_observed_window_mean':float(r.prior_events_mean_7d),'volume_deviation':float(r.volume_deviation),
                'new_hosts':float(r.new_hosts),'history_windows':float(r.prior_observed_windows_7d),
                'evidence_record_ids':list(r.record_ids)[:5],'window_start':r.window_start,'window_unit':'hour'}
            predictions.append({'window_id':r.window_id,'user':r.user,'window_start':r.window_start,'events':int(r.event_count),'risk_score':float(score[i]),'risk_tier':str(tiers[i]),'prediction':flagged,'components':{k:float(v[i]) for k,v in components.items() if k!='supervised'},'explanation':explanation,'alert_id':alert_id})
            if flagged:alerts.append(InferenceAlert(id=alert_id,run_id=run_id,window_id=r.window_id,severity=str(tiers[i])))
        db.add(InferenceRun(id=run_id,dataset_id=dataset_id,model_version=row.id,parent_id=parent,context_token=token,
            coverage_start=str(start),coverage_end=str(end),actor=actor,input_sha256=payload_sha,
            provenance={'source_kind':settings['source_kind'],'description':description,'profile':settings['profile'],
             'completeness':'Operator-attested, not independently verified; all users in registered stream.','scope':'NEW_INFERENCE_ONLY; no labels, no benchmark metrics or independence claim'},
            events=canonical_records(new),features=canonical_records(features),predictions=predictions))
        db.flush();db.add_all(alerts)
        db.add(AuditLog(actor=actor,action='inference.import',target=run_id,details={'model_version':row.id,'events':len(new),'windows':len(features),'input_sha256':payload_sha}))
        return {'run_id':run_id,'reused':False}
