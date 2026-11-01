"""Causal features, untouched test exclusion, and source-backed representative replay."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from src.evaluation.spedia_experiment import EventFeatures,EXTRA,threshold
from src.db.replay import load_replay


def events():
    return pd.DataFrame([dict(user='u',host=host,time=pd.Timestamp('2025-01-01')+pd.Timedelta(seconds=t),source_record_id=str(i),Activity='command',Action='Execute',Command=cmd) for i,(t,host,cmd) in enumerate([(0,'a','ls'),(10,'a','ls'),(600,'b','rare-command'),(3600,'a','ls'),(7200,'a','later')])]).assign(window_start=lambda f:f.time.dt.floor('h'))


def test_features_ignore_labels_and_future_and_freeze_vocabulary():
    frame=events();encoder=EventFeatures().fit(frame.iloc[:2]);before=dict(encoder.commands)
    a=encoder.transform(frame.assign(Anomaly=0));changed=frame.copy()
    changed.loc[4,'Command']='unseen-future';changed.loc[4,'host']='other'
    b=encoder.transform(changed.assign(Anomaly=1))
    pd.testing.assert_frame_equal(a.iloc[:2],b.iloc[:2])
    assert dict(encoder.commands)==before
    assert a.iloc[0].command_surprise_max>a.iloc[1].command_surprise_max
    assert a.iloc[0].idle_sessions==2
    assert a.iloc[1].cold_start==0
    assert a.iloc[1].new_user_host_action_fraction==0
    assert np.isfinite(a[EXTRA].to_numpy()).all()


def test_raw_threshold_not_clipped_to_percentiles():
    assert threshold([0,0,1,1],[10,100,1000,1001])==1000


@pytest.mark.skipif(not Path('data/spedia/experiment-v5/report.json').exists(),reason='Local experiment not generated')
def test_new_experiment_excludes_old_test_and_compares_four_models():
    root=Path('data/spedia/experiment-v5');plan=json.loads((root/'plan.json').read_text())
    old=pd.read_parquet('data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223/scores.parquet')
    forbidden=set(old.loc[old.split=='test','window_id'])
    assert forbidden.isdisjoint(plan['training_window_ids']+plan['validation_window_ids'])
    diagnostics=pd.read_parquet(root/'validation_diagnostics.parquet')
    assert set(diagnostics.window_id)==set(plan['validation_window_ids'])
    report=json.loads((root/'report.json').read_text())
    for result in report['results'].values():
        assert set(result)=={'isolation_forest','pca','neural_autoencoder','supervised_logistic'}
    assert plan['final_test']['records_reserved']==0


@pytest.mark.skipif(not Path('data/spedia/replay-realistic-v1').exists(),reason='Genuine local replay unavailable')
def test_realistic_replay_has_every_retained_test_hour_without_selection():
    manifest,frame=load_replay('data/spedia/replay-realistic-v1')
    old=pd.read_parquet('data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223/scores.parquet')
    test=old.loc[old.split=='test'].sort_values(['window_start','user'])
    assert frame.window_id.tolist()==test.window_id.tolist()
    assert not set(frame)&{'Anomaly','label','outcome','risk_score'}
    source=pd.read_parquet('data/spedia/replay-realistic-v1/replay_events.parquet')
    assert source.time.is_monotonic_increasing
    assert len(source)==manifest['events']==sum(map(len,frame.record_ids))
    assert set(source.source_record_id)=={rid for ids in test.record_ids for rid in ids}
