"""Frozen-test proxy-group coverage; positive-only, never an independent benchmark."""
import argparse,json
from pathlib import Path
import pandas as pd
from src.data.spedia import load_spedia,prepare_events
from src.data.integrity import atomic_json, sha256_file


def coverage(review_directory,source,output):
    root=Path(review_directory);target=Path(output)
    if target.exists():raise FileExistsError('Preserve the previous coverage result')
    audit=json.loads((root/'review.json').read_text())
    expected=audit['input_checksums'].get(str(Path(source)))
    if expected is None or sha256_file(source)!=expected:raise ValueError('Source differs from frozen review')
    events,_=prepare_events(load_spedia(source))
    windows=pd.read_parquet(root/'window_diagnostics.parquet')
    # Source time is datetime; diagnostics persist its source wall-clock string.
    events['window_start']=events.window_start.astype(str)
    joined=events.loc[(events.split=='test')&events.scenario_proxy.notna()].merge(windows,on=['user','window_start'],how='inner')
    groups=[]
    for proxy,g in joined.groupby('scenario_proxy'):
        hours=g.drop_duplicates('window_id');flagged=hours.score>=audit['original_operating_point']['threshold']
        groups.append({'scenario_proxy':proxy,'events':len(g),'users':sorted(g.user.unique()),'test_hours':len(hours),'flagged_hours':int(flagged.sum()),'hour_coverage':float(flagged.mean()),'median_events_per_hour':float(hours.event_count.median()),'median_score':float(hours.score.median())})
    result={'model_version':audit['model_version'],'groups':groups,'warning':'Source hash suffix is an unverified scenario proxy. Groups can share user-hours; counts are not additive. This cohort is positive-only; no within-cohort specificity, AP or independent-generalization claim is possible.'}
    atomic_json(target,result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--review',default='data/spedia/review-v3');p.add_argument('--source',default='logs_SPEDIA_annotated_en.csv');p.add_argument('--output',required=True);a=p.parse_args();r=coverage(a.review,a.source,a.output);print('Proxy groups:',len(r['groups']));print(r['warning'])
