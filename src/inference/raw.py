"""Strict raw SPEDIA-compatible parsing and reuse of the original causal features."""
import csv
import hashlib
import io
import math
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.integrity import sha256_file
from src.data.spedia import ACTIVITIES, FEATURE_NAMES, aggregate_windows

RAW_COLUMNS=['id','User','Timestamp','Agent_name','Activity','Action','Command','Filename','Path','To','Cc','Bcc',
             'Attachments','Size','Size_before','Size_after']
NUMERIC=['Attachments','Size','Size_before','Size_after']
CONTEXT_COLUMNS=['source_record_id','user','time','host','Activity','Action','Command','Filename','Path','To','Cc','Bcc',*NUMERIC]
ACTIONS={'command':{'Command executed'},'device':{'Connect','Disconnect'},'email':{'Email sent'},
         'file':{'File accessed','File added','File deleted','File modified'},'http':{'URL accedida'},
         'session':{'Login','Logoff','Login Failed'}}
MAX_BYTES=256*1024
MAX_EVENTS=1000


class InputError(ValueError):
    pass


def timestamp(value):
    try:
        result=pd.Timestamp(value)
        if pd.isna(result) or result.tzinfo is not None:raise ValueError()
        return result
    except (ValueError,TypeError,OverflowError):
        raise InputError('Use source wall-clock timestamps without a timezone; the SPEDIA contract has no supplied timezone.') from None


def load_context(directory):
    root=Path(directory)
    try:
        manifest=json.loads((root/'context.json').read_text())
        if sha256_file(root/'events.parquet')!=manifest['events_sha256']:raise InputError('Historical context checksum mismatch.')
        frame=pd.read_parquet(root/'events.parquet')
    except (OSError,KeyError,json.JSONDecodeError):
        raise InputError('Verified label-free historical context is unavailable; provision it offline first.') from None
    if list(frame)!=CONTEXT_COLUMNS or manifest['feature_version']!='spedia-hour-v1':raise InputError('Historical context contract is incompatible.')
    return manifest,frame


def parse_csv(content,coverage_start,coverage_end):
    if not content or len(content)>MAX_BYTES:raise InputError('CSV must be nonempty and at most 256 KiB.')
    try:
        decoded=content.decode('utf-8-sig')
        header=next(csv.reader(io.StringIO(decoded)))
        if len(header)!=len(set(header)):raise InputError('Duplicate CSV column names are not permitted.')
        missing=set(RAW_COLUMNS)-set(header);extra=set(header)-set(RAW_COLUMNS)
        if missing:raise InputError('Missing required supported columns: '+', '.join(sorted(missing)))
        if extra:raise InputError('Unsupported columns (labels/annotations must stay outside inference): '+', '.join(sorted(extra)))
        frame=pd.read_csv(io.StringIO(decoded),dtype=str,keep_default_na=False,on_bad_lines='error')
    except (UnicodeError,pd.errors.ParserError,pd.errors.EmptyDataError,StopIteration,csv.Error):
        raise InputError('CSV must be valid UTF-8 with a header and consistent rows.') from None
    if not 1<=len(frame)<=MAX_EVENTS:raise InputError('Supply 1–1000 events.')
    for name in RAW_COLUMNS:frame[name]=frame[name].str.strip().replace('',pd.NA)
    for name in ('id','User','Timestamp','Agent_name','Activity','Action'):
        if frame[name].isna().any():raise InputError(f'{name} cannot be empty.')
    if frame[['id','User','Agent_name']].map(lambda x:len(x)>256).any().any():raise InputError('Identifiers must have at most 256 characters.')
    if frame.id.duplicated().any():raise InputError('Duplicate event IDs are not permitted.')
    if not frame.Activity.isin(ACTIVITIES).all():raise InputError('Unsupported Activity; supported values: '+', '.join(ACTIVITIES))
    if any(action not in ACTIONS[activity] for activity,action in zip(frame.Activity,frame.Action)):
        raise InputError('Action does not match the supported SPEDIA Activity vocabulary; incompatible telemetry must not be coerced into this schema.')
    times=[timestamp(x) for x in frame.Timestamp]
    frame['time']=pd.to_datetime(times)
    if not ((frame.time>=coverage_start)&(frame.time<coverage_end)).all():raise InputError('Every event timestamp must be inside the declared closed-hour coverage interval.')
    for name in NUMERIC:
        values=pd.to_numeric(frame[name],errors='coerce')
        invalid=(frame[name].notna()&values.isna()) | (values.notna()&(~np.isfinite(values)| (values<0)))
        if invalid.any():raise InputError(f'{name} must contain finite nonnegative native-unit numbers or an applicable empty value.')
        frame[name]=values.astype(float)
    if frame.loc[frame.Activity.eq('command'),'Command'].isna().any():raise InputError('Command activity requires the observed Command field.')
    email=frame.Activity.eq('email')
    if frame.loc[email,['To','Attachments','Size']].isna().any().any():raise InputError('Email activity requires observed To, Attachments and Size fields in source-native units.')
    files=frame.Activity.eq('file')
    if (frame.loc[files,'Path'].isna()&frame.loc[files,'Filename'].isna()).any():raise InputError('File activity requires an observed Path or Filename.')
    if frame.drop(columns='id').duplicated().any():raise InputError('Duplicate activity rows with different IDs are not permitted.')
    frame['source_record_id']=frame.id
    frame['user']=frame.User
    frame['host']=frame.Agent_name.str.replace(r'_(?:simulation|[a-f0-9]{40})$','',regex=True)
    if frame.host.eq('').any():raise InputError('Observed host is empty after source-contract normalization.')
    return frame[CONTEXT_COLUMNS].copy()


def canonical_records(frame):
    # pandas.to_json defaults to 10-digit floats, which would change historical
    # numeric context and saved feature vectors after a database round trip.
    def normalize(value):
        if value is None or value is pd.NA or value is pd.NaT:return None
        if isinstance(value,pd.Timestamp):return value.isoformat(sep=' ')
        if isinstance(value,np.ndarray):return [normalize(x) for x in value]
        if isinstance(value,np.generic):return normalize(value.item())
        if isinstance(value,dict):return {k:normalize(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [normalize(v) for v in value]
        if isinstance(value,float) and not math.isfinite(value):return None
        return value
    records=normalize(frame.to_dict('records'))
    json.dumps(records,allow_nan=False) # Native JSON float repr preserves round trips.
    return records


def from_records(records):
    frame=pd.DataFrame(records,columns=CONTEXT_COLUMNS)
    frame['time']=pd.to_datetime(frame.time)
    for name in NUMERIC:frame[name]=pd.to_numeric(frame[name],errors='coerce')
    for name in set(CONTEXT_COLUMNS)-set(NUMERIC)-{'time'}:frame[name]=frame[name].replace({None:np.nan})
    return frame


def generate_features(context,new_events,time_origin):
    """Pure computation: no labels, fitting, calibration or evaluation artifacts."""
    if set(new_events.source_record_id)&set(context.source_record_id):raise InputError('Previously observed event IDs cannot be imported again.')
    # Personal features are independent across users; avoid recomputing unrelated accounts.
    context=context.loc[context.user.isin(new_events.user.unique())].copy()
    for user,group in new_events.groupby('user'):
        history=context.loc[context.user==user]
        first=group.time.min().floor('h')
        if history.empty:raise InputError(f'No verified historical context for user {user!r}; cold-start inference is not enabled.')
        if not ((history.time>=first-pd.Timedelta(days=7))&(history.time<first)).any():raise InputError(f'No observed activity in the prior seven days for user {user!r}; provide verified context rather than fabricated baselines.')
    # Retain all earlier observed activity for cumulative novelty; rolling moments
    # still use only [t-168h,t). No future records can be admitted by API continuity.
    combined=pd.concat([context,new_events],ignore_index=True).sort_values(['time','source_record_id'])
    combined['window_start']=combined.time.dt.floor('h')
    combined['window_index']=((combined.window_start-pd.Timestamp(time_origin)).dt.total_seconds()/3600).astype(int)
    combined['split']='inference'
    table,_,_=aggregate_windows(combined)
    first=new_events.time.min().floor('h')
    selected=table.loc[pd.to_datetime(table.window_start)>=first].copy()
    selected=selected.drop(columns=['label','attack_event_count'])
    if not np.isfinite(selected[FEATURE_NAMES].to_numpy(dtype=float)).all():raise InputError('Feature contract produced nonfinite values.')
    return selected
