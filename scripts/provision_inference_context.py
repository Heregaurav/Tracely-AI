"""Offline context provisioning; label handling stays outside request-time inference.

Reconstructs the original curated event context, verifies all published feature
vectors, then exports ONLY fields consumed by causal feature generation.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from src.data.spedia import load_spedia,prepare_events,aggregate_windows,FEATURE_NAMES
from src.data.integrity import atomic_json, sha256_file
from src.inference.raw import CONTEXT_COLUMNS


def provision(source,features,output):
    source,features,output=map(Path,(source,features,output))
    if output.exists():raise FileExistsError('Context snapshots are immutable; choose a new directory.')
    report=json.loads(features.with_suffix('.json').read_text())
    if sha256_file(source)!=report['provenance']['sha256'] or sha256_file(features)!=report['features_sha256']:raise ValueError('Original source/features checksum mismatch')
    events,audit=prepare_events(load_spedia(source))
    actual,_,_=aggregate_windows(events)
    expected=pd.read_parquet(features).set_index('window_id').sort_index()
    actual=actual.set_index('window_id').sort_index()
    if list(actual.index)!=list(expected.index):raise ValueError('Context reconstruction changed original windows')
    np.testing.assert_array_equal(actual[FEATURE_NAMES].to_numpy(),expected[FEATURE_NAMES].to_numpy())
    snapshot=events[CONTEXT_COLUMNS].copy()
    snapshot['time']=pd.to_datetime(snapshot.time)
    # Future uploads extend only closed observation hours after all source activity.
    next_hour=events.time.max().floor('h')+pd.Timedelta(hours=1)
    output.mkdir(parents=True)
    snapshot.to_parquet(output/'events.parquet',index=False)
    manifest={'feature_version':report['feature_version'],'dataset_id':report['dataset_id'],'source_sha256':sha256_file(source),
       'features_sha256':sha256_file(features),'events_sha256':sha256_file(output/'events.parquet'),'events':len(snapshot),
       'time_origin':audit['time_origin'],'next_coverage_start':str(next_hour),'coverage_start':str(events.time.min().floor('d')),
       'source_policy':'Exact original curated experimental context, including pre-window-dedup history; not complete enterprise telemetry.',
       'verification':'Every original saved numerical feature vector reproduced exactly. Snapshot contains no labels or annotation fields.'}
    atomic_json(output/'context.json',manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k!='source_sha256'},indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',default='logs_SPEDIA_annotated_en.csv');p.add_argument('--features',default='data/spedia/features-temporal/features.parquet');p.add_argument('--output',required=True);a=p.parse_args();provision(a.source,a.features,a.output)
