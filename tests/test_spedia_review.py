"""Small fixtures for safeguards; actual frozen-data regression checks are explicit."""
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pytest
from src.data.spedia import FEATURE_NAMES,aggregate_windows,load_spedia
from src.evaluation.spedia_review import operating_points
from src.db.replay import load_replay
from src.models.behavioral import metrics


def test_validation_operating_points_and_undefined_metrics():
    y=np.array([0,0,0,1,1,1],dtype=bool);s=np.array([1,20,70,30,80,95.])
    policies=operating_points(y,s)
    assert policies['precision_focused']['precision']>=.9
    assert policies['recall_focused']['recall']>=policies['precision_focused']['recall']
    assert metrics([0,0],[10,30],50)['pr_auc_average_precision'] is None
    assert metrics([0,0],[10,30],50)['recall'] is None
    assert metrics([0,1],[10,90],50)['confusion_matrix']==[[1,0],[0,1]]


def test_past_only_history_and_no_target_feature():
    def make(future,label):
        rows=[]
        for hour,count in [(0,2),(1,3),(2,future)]:
            for n in range(count):
                rows.append(dict(user='fixture-user',window_start=pd.Timestamp('2025-01-01')+pd.Timedelta(hours=hour),window_index=hour,time=pd.Timestamp('2025-01-01')+pd.Timedelta(hours=hour,seconds=n),source_record_id=f'{hour}-{n}',split='train',Anomaly=label,Activity='session',Action='Login',host='fixture-host'))
        return aggregate_windows(pd.DataFrame(rows))[0]
    original=make(4,0);changed=make(100,1)
    pd.testing.assert_frame_equal(original.loc[:1,FEATURE_NAMES],changed.loc[:1,FEATURE_NAMES])
    assert original.loc[1,'prior_events_mean_7d']==2
    assert original.loc[2,'prior_events_mean_7d']==2.5
    assert not set(FEATURE_NAMES)&{'Anomaly','label','Agent_name','User','scenario_proxy','Description','Level','simulation_marker','Decoder_name'}


ROOT=Path('data/spedia/review-v3')
RUN=Path('data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223')

@pytest.mark.skipif(not ROOT.exists(),reason='Genuine local SPEDIA review artifacts unavailable')
def test_actual_replay_is_complete_unseen_and_label_free():
    manifest,inputs=load_replay(ROOT)
    scores=pd.read_parquet(RUN/'scores.parquet');test=scores.loc[scores.split=='test']
    assert set(inputs.window_id)<=set(test.window_id)
    assert set(inputs.window_id).isdisjoint(scores.loc[scores.split!='test','window_id'])
    assert not set(inputs)&{'label','Anomaly','outcome','predicted_attack','risk_score'}
    assert 100<=manifest['events']<=300
    event_ids=set(pd.read_parquet(ROOT/'replay_events.parquet').source_record_id)
    for row in inputs.itertuples():
        source=test.loc[test.window_id==row.window_id].iloc[0]
        assert list(row.record_ids)==list(source.record_ids)
        assert set(row.record_ids)<=event_ids
        np.testing.assert_array_equal(inputs.loc[inputs.window_id==row.window_id,FEATURE_NAMES].to_numpy(),source[FEATURE_NAMES].to_numpy()[None,:])
    truth=json.loads((ROOT/'replay_ground_truth.json').read_text())
    assert {'TN','TP','FN','FP'}=={w['example_outcome'] for w in truth['windows']}


@pytest.mark.skipif(not ROOT.exists(),reason='Genuine local SPEDIA review artifacts unavailable')
def test_actual_frozen_model_has_no_fit_and_matches_publication(monkeypatch):
    _,inputs=load_replay(ROOT);model=joblib.load(RUN/'model.joblib');before=joblib.hash(model)
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import IsolationForest
    def forbidden(*a,**k):raise AssertionError('Replay must not fit')
    monkeypatch.setattr(StandardScaler,'fit',forbidden);monkeypatch.setattr(IsolationForest,'fit',forbidden)
    score=model.score(inputs[model.names])[0];saved=pd.read_parquet(RUN/'scores.parquet').set_index('window_id')
    np.testing.assert_allclose(score,saved.loc[inputs.window_id,'risk_score'],rtol=0,atol=1e-9)
    assert joblib.hash(model)==before
    audit=json.loads((ROOT/'review.json').read_text())
    assert audit['original_operating_point']['confusion_matrix']==[[222,14],[99,86]]
    assert audit['splits']['test']==dict(windows=421,positive=185,negative=236,prevalence=185/421,random_ranking_pr_ap_baseline=185/421)


def test_replay_checksum_rejects_corrupt_input(tmp_path):
    (tmp_path/'replay_manifest.json').write_text(json.dumps({'inputs_sha256':'0'*64}))
    (tmp_path/'replay_inputs.parquet').write_bytes(b'broken')
    with pytest.raises(ValueError,match='checksum'):load_replay(tmp_path)


@pytest.mark.skipif(not ROOT.exists(),reason='Genuine SPEDIA review artifacts unavailable')
def test_original_experiment_files_remain_byte_identical():
    from src.data.integrity import sha256_file
    audit=json.loads((ROOT/'review.json').read_text())
    for file,digest in audit['input_checksums'].items():
        assert sha256_file(file)==digest,file
    ablation=json.loads(Path('data/spedia/supervised-audit-v1/plan.json').read_text())
    original=pd.read_parquet('data/spedia/features-temporal/features.parquet')
    test_ids=set(original.loc[original.split=='test','window_id'])
    assert test_ids.isdisjoint(ablation['training_window_ids'])
    assert test_ids.isdisjoint(ablation['validation_window_ids'])
