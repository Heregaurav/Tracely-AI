"""Engineering fixtures test shared ML contracts, never published detection quality."""
import joblib
import numpy as np
import pandas as pd
import pytest
from src.data.spedia import FEATURE_NAMES,contract
from src.models.behavioral import BehavioralDetector,metrics
from src.models.scoring import combine,percentile_scores


def fixture_frame(count,seed):
    rng=np.random.default_rng(seed)
    frame=pd.DataFrame(rng.uniform(0,10,(count,len(FEATURE_NAMES))),columns=FEATURE_NAMES)
    frame['label']=[i%4==0 for i in range(count)]
    return frame


def test_train_only_scaling_order_roundtrip_and_frozen_reference(tmp_path):
    train=fixture_frame(24,1);val=fixture_frame(12,2)
    model=BehavioralDetector(contract(),estimators=8,neural=False).fit(train,val)
    np.testing.assert_allclose(model.scaler.mean_,train.loc[~train.label,FEATURE_NAMES].mean())
    expected=model.score(val)[0]
    np.testing.assert_array_equal(expected,model.score(val[val.columns[::-1]])[0])
    before=joblib.hash(model);joblib.dump(model,tmp_path/'model.joblib')
    np.testing.assert_array_equal(expected,joblib.load(tmp_path/'model.joblib').score(val)[0])
    heldout=fixture_frame(8,3);heldout[FEATURE_NAMES]=1e6
    assert model.raw(heldout)['pca'].mean()>model.raw(val)['pca'].mean()
    model.score(heldout)
    assert joblib.hash(model)==before
    with pytest.raises(ValueError,match='feature contract'):model.score(val.drop(columns=FEATURE_NAMES[0]))


def test_neural_autoencoder_uses_temporal_validation_checkpoint():
    train=fixture_frame(24,4);val=fixture_frame(12,5)
    model=BehavioralDetector(contract(),estimators=5,epochs=3,neural=True).fit(train,val)
    assert model.neural is not None and model.neural.hidden_layer_sizes==(24,8,24)
    assert 1<=len(model.neural_history)<=3
    assert model.neural.predict(model.scaler.transform(model.matrix(val))).shape==(12,len(FEATURE_NAMES))
    assert model.supervised is not None # Explicit labeled-training comparator, never active.
    assert not model.active.startswith('supervised')


def test_shared_midrank_and_explicit_ensemble_contract():
    np.testing.assert_allclose(percentile_scores([0,1,2,3],[1,1,2]),[0,100/3,250/3,100],rtol=0,atol=1e-12)
    np.testing.assert_allclose(combine({'if':np.array([10]),'pca':np.array([20])},{'if':.6,'pca':.4}),[14])
    for weights in ({'if':-1},{'if':.6,'graph':.4}):
        with pytest.raises(ValueError):combine({'if':np.array([10])},weights)
    with pytest.raises(ValueError):percentile_scores([1],[])
    assert metrics([0,0],[20,90],85)['recall'] is None
