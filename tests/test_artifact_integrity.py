"""Shared integrity helpers preserve historical contracts and refuse unverified loads."""
import hashlib
import json
import pytest
from src.data import integrity
from src.inference.artifacts import load_verified_model
from src.inference.raw import InputError


def test_shared_json_bytes_remain_compatible(tmp_path):
    path=tmp_path/'nested'/'manifest.json'
    value={'windows':[1,2],'label':False}
    integrity.atomic_json(path,value)
    assert path.read_text()==json.dumps(value,indent=2)
    assert integrity.sha256_file(path)==hashlib.sha256(path.read_bytes()).hexdigest()
    assert not path.with_suffix('.json.tmp').exists()


@pytest.mark.parametrize('error_type',[ValueError,InputError])
def test_checksum_is_verified_before_deserialization(tmp_path,monkeypatch,error_type):
    artifact=tmp_path/'model.joblib';artifact.write_bytes(b'untrusted bytes')
    calls=[]
    monkeypatch.setattr('src.inference.artifacts.joblib.load',lambda path:calls.append(path) or 'verified model')
    with pytest.raises(error_type,match='checksum mismatch'):
        load_verified_model(artifact,'0'*64,error_type=error_type)
    assert not calls
    assert load_verified_model(artifact,integrity.sha256_file(artifact))=='verified model'
    assert calls==[artifact]
