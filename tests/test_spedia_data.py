"""Native CSV validation, causal feature construction and immutable output guards."""
import json
import pandas as pd
import pytest
from src.data.spedia import load_spedia,build_spedia,FEATURE_NAMES


def native_csv(tmp_path):
    rows=[]
    for day in range(10):
        for user in range(3):
            for event in range(2+day%3):
                rows.append(dict(id=f'engineering-{day}-{user}-{event}',Agent_name=f'host-{user}_simulation',User=f'u{user}',
                    Timestamp=str(pd.Timestamp('2025-01-01')+pd.Timedelta(days=day,hours=user,seconds=event)),
                    Decoder_name='engineering-fixture',Activity='command',Action='Command executed',
                    Command=f'fixture-command-{day}-{event}',Anomaly=int(user==2)))
    path=tmp_path/'native-engineering.csv';pd.DataFrame(rows).to_csv(path,index=False)
    return path


def test_native_ingestion_features_provenance_splits_and_no_overwrite(tmp_path):
    source=native_csv(tmp_path);events=load_spedia(source)
    assert len(events)==87
    report=build_spedia(source,tmp_path/'features')
    assert report['family']=='spedia' and report['is_fixture']
    frame=pd.read_parquet(tmp_path/'features/features.parquet')
    assert set(frame.split)=={'train','validation','test'}
    assert all(frame[FEATURE_NAMES].dtypes=='float64')
    times={s:pd.to_datetime(g.window_start) for s,g in frame.groupby('split')}
    assert times['train'].max()<times['validation'].min()<times['test'].min()
    manifest=json.loads((tmp_path/'features/split_manifest.json').read_text())
    ids=[set(m['record_ids']) for m in manifest['splits'].values()]
    assert all(a.isdisjoint(b) for i,a in enumerate(ids) for b in ids[i+1:])
    with pytest.raises(FileExistsError):build_spedia(source,tmp_path/'features')


def test_native_source_rejects_invalid_labels_and_timestamps(tmp_path):
    path=native_csv(tmp_path);frame=pd.read_csv(path)
    frame.loc[0,'Anomaly']=2;frame.to_csv(path,index=False)
    with pytest.raises(ValueError,match='binary'):load_spedia(path)
    frame.loc[0,'Anomaly']=0;frame.loc[0,'Timestamp']='invalid';frame.to_csv(path,index=False)
    with pytest.raises(ValueError,match='timestamps'):load_spedia(path)
