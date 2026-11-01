"""Engineering fixtures only; no real-world performance claims."""
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pytest
from src.inference.raw import (RAW_COLUMNS,CONTEXT_COLUMNS,InputError,parse_csv,load_context,generate_features,canonical_records,from_records)

START=pd.Timestamp('2025-03-30 20:00:00');END=START+pd.Timedelta(hours=1)
CONTEXT=Path('data/inference/context-v1')
MODEL=Path('data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223')


def fixture_csv(count=120,*,start=START,prefix='engineering-fixture',user='irene'):
    rows=[]
    for i in range(count):
        r={name:'' for name in RAW_COLUMNS}
        r.update(id=f'{prefix}-{i}',User=user,Timestamp=str(start+pd.Timedelta(seconds=i)),Agent_name=f'fixture-host-{i}',Activity='command',Action='Command executed',Command=f'engineering-test-command-{i}')
        rows.append(r)
    return pd.DataFrame(rows).to_csv(index=False).encode()


def settings(token,*,start=START,end=END):
    return {'context_token':token,'coverage_start':str(start),'coverage_end':str(end),'complete_hours':'true','profile':'spedia-v2-native',
            'source_kind':'engineering-test-fixture','provenance':'ENGINEERING TEST FIXTURE: generated events for software verification; not independent real activity or model evaluation.'}


def test_parse_normalizes_and_preserves_native_missing_values():
    frame=parse_csv(fixture_csv(3),START,END)
    assert list(frame)==CONTEXT_COLUMNS and len(frame)==3
    assert frame.Size.isna().all()
    assert not set(frame)&{'label','Anomaly','Description','Level','Decoder_name','simulation_marker'}
    pd.testing.assert_frame_equal(from_records(canonical_records(frame)).fillna('<missing>'),frame.fillna('<missing>'),check_dtype=False)


@pytest.mark.parametrize('mutation,match',[
    (lambda f:f.assign(Anomaly=1),'labels/annotations'),
    (lambda f:f.drop(columns='Size'),'Missing required'),
    (lambda f:f.assign(Activity='unknown'),'Unsupported Activity'),
    (lambda f:f.assign(Action='Suspicious analyst annotation'),'Action does not match'),
    (lambda f:f.assign(Timestamp='2025-03-30T20:01:00Z'),'without a timezone'),
    (lambda f:f.assign(Timestamp='not-a-date'),'timestamps'),
    (lambda f:f.assign(Size='infinity'),'finite nonnegative'),
    (lambda f:f.assign(id='duplicate'),'Duplicate event IDs'),
    (lambda f:f.assign(Command=''),'requires the observed'),
    (lambda f:f.assign(User=''),'User cannot be empty'),
])
def test_rejects_incompatible_raw_fields(mutation,match):
    frame=pd.read_csv(__import__('io').BytesIO(fixture_csv(3)),keep_default_na=False)
    with pytest.raises(InputError,match=match):parse_csv(mutation(frame).to_csv(index=False).encode(),START,END)


def test_size_and_coverage_guards():
    with pytest.raises(InputError,match='256 KiB'):parse_csv(b'x'*(256*1024+1),START,END)
    with pytest.raises(InputError,match='inside the declared'):parse_csv(fixture_csv(1,start=START-pd.Timedelta(hours=1)),START,END)
    with pytest.raises(InputError,match='Duplicate CSV'):parse_csv(b'id,id\n1,2',START,END)


@pytest.mark.skipif(not CONTEXT.exists(),reason='Original verified context unavailable')
def test_actual_context_features_are_causal_label_free_and_frozen(monkeypatch):
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import IsolationForest
    def forbidden(*a,**k):raise AssertionError('No fitting is permitted')
    monkeypatch.setattr(StandardScaler,'fit',forbidden);monkeypatch.setattr(IsolationForest,'fit',forbidden)
    manifest,context=load_context(CONTEXT)
    assert not set(context)&{'Anomaly','label','Description','Full_log','Level'}
    new=parse_csv(fixture_csv(),START,END)
    features=generate_features(context,new,manifest['time_origin'])
    model=joblib.load(MODEL/'model.joblib');before=joblib.hash(model)
    first=model.score(features[model.names])[0]
    assert np.isfinite(first).all() and (first>=model.threshold).any(),'Fixture must exercise model-generated alerts'
    restored=joblib.load(MODEL/'model.joblib');np.testing.assert_array_equal(first,restored.score(features[model.names])[0])
    assert before==joblib.hash(model)
    with pytest.raises(InputError,match='No verified historical'):generate_features(context,new.assign(user='unknown-fixture-user'),manifest['time_origin'])
    with pytest.raises(InputError,match='Previously observed'):generate_features(context,new.assign(source_record_id=context.source_record_id.iloc[0]),manifest['time_origin'])
    future=parse_csv(fixture_csv(3,start=END,prefix='fixture-future'),END,END+pd.Timedelta(hours=1))
    extended=generate_features(context,pd.concat([new,future]),manifest['time_origin'])
    np.testing.assert_array_equal(features[model.names].to_numpy(),extended.iloc[:1][model.names].to_numpy())
