"""Frozen SPEDIA replay. Labels never enter the inference path."""
import hashlib
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.data.integrity import sha256_file
from src.data.neon_assets import resolve_asset_path
from src.inference.artifacts import load_verified_model
from .models import Alert, AuditLog, DailyScore, ModelVersion, ReplayRun


def load_replay(directory):
    root=Path(directory);manifest=json.loads((root/'replay_manifest.json').read_text())
    for name,key in [('replay_inputs.parquet','inputs_sha256'),('replay_events.parquet','events_sha256')]:
        if sha256_file(root/name)!=manifest[key]:raise ValueError('Replay checksum mismatch')
    frame=pd.read_parquet(root/'replay_inputs.parquet')
    if len(frame)!=manifest['windows'] or set(frame.window_id)!=set(manifest['window_ids']):raise ValueError('Replay manifest does not match windows')
    return manifest,frame


def execute_replay(factory,directory,*,actor,dataset_id):
    started=time.perf_counter(); timings={}
    manifest,frame=load_replay(directory)
    timings['input_integrity_and_load_ms']=(time.perf_counter()-started)*1000
    database_start=time.perf_counter()
    run_id=hashlib.sha256((manifest['model_version']+'|'+manifest['inputs_sha256']).encode()).hexdigest()
    with factory.begin() as db:
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':run_id})
        previous=db.get(ReplayRun,run_id)
        if previous:return {'run_id':run_id,'predictions':previous.predictions,'reused':True,'timings':{**timings,'cached_database_ms':(time.perf_counter()-database_start)*1000,'total_ms':(time.perf_counter()-started)*1000}}
        model_row=db.get(ModelVersion,manifest['model_version'])
        if model_row is None or not model_row.active or model_row.dataset_id!=dataset_id or model_row.report.get('family')!='spedia':raise ValueError('Publish the matching SPEDIA model first')
        timings['database_lookup_ms']=(time.perf_counter()-database_start)*1000
        load_start=time.perf_counter()
        artifact=resolve_asset_path(model_row.artifact_path)/'model.joblib'
        model=load_verified_model(artifact,model_row.artifact_sha256);before=joblib.hash(model)
        timings['model_load_and_integrity_ms']=(time.perf_counter()-load_start)*1000
        inference_start=time.perf_counter()
        index,tiers,components=model.score(frame[model.names]) # No target or investigation metadata.
        if before!=joblib.hash(model):raise ValueError('Inference changed the model')
        timings['inference_and_mutation_check_ms']=(time.perf_counter()-inference_start)*1000
        database_start=time.perf_counter()
        scores={(s.user,s.relative_day):s for s in db.scalars(select(DailyScore).where(DailyScore.model_version==model_row.id,DailyScore.relative_day.in_([int(v) for v in frame.window_index.unique()]),DailyScore.user.in_(frame.user.unique().tolist())))}
        predictions=[]; alerts=[]
        for i,r in enumerate(frame.itertuples()):
            score=scores.get((r.user,int(r.window_index)))
            if score is None:raise ValueError('Matching published window is missing')
            if not np.isclose(score.risk_score,index[i],rtol=0,atol=1e-9):raise ValueError('Replay differs from immutable published score')
            alert_id=None
            if index[i]>=model.threshold:
                alert_id=score.id
                alerts.append(dict(id=score.id,score_id=score.id,severity=str(tiers[i]),status='OPEN',version=1))
            predictions.append({'window_id':r.window_id,'user':r.user,'window_start':r.window_start,'events':len(r.record_ids),
                'risk_score':float(index[i]),'risk_tier':str(tiers[i]),'prediction':bool(index[i]>=model.threshold),
                'components':{k:float(v[i]) for k,v in components.items()},'explanation':score.explanation,'alert_id':alert_id})
        if alerts:db.execute(insert(Alert).values(alerts).on_conflict_do_nothing())
        timings['database_scores_and_alerts_ms']=(time.perf_counter()-database_start)*1000
        timings['total_before_commit_ms']=(time.perf_counter()-started)*1000
        db.add(ReplayRun(id=run_id,dataset_id=dataset_id,model_version=model_row.id,actor=actor,inputs_sha256=manifest['inputs_sha256'],predictions=predictions))
        db.add(AuditLog(actor=actor,action='replay.detect',target=run_id,details={'windows':len(frame),'model_version':model_row.id,'timings':timings}))
        return {'run_id':run_id,'predictions':predictions,'reused':False,'timings':timings}
