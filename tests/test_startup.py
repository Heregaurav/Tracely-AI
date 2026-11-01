"""Exercise startup selection without opening ports, running migrations or training."""
import json
import os
from pathlib import Path
import subprocess


def test_startup_serves_without_training_or_generation(tmp_path):
    log=tmp_path/'calls.jsonl'
    # Both executable stubs finish after all child commands have been launched.
    stub=f'#!/usr/bin/env python3\nimport json,sys,time\nwith open({str(log)!r},"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\ntime.sleep(.25)\n'
    for name in ['python-stub','npm']:
        path=tmp_path/name;path.write_text(stub);path.chmod(0o700)
    env={**os.environ,'DATABASE_URL':'postgresql://unused/test','SESSION_SECRET':'stub-only-'+'x'*40,
         'DATASET_ID':'spedia-v2','PYTHON':str(tmp_path/'python-stub'),'PATH':str(tmp_path)+os.pathsep+os.environ['PATH']}
    subprocess.run(['bash','start.sh'],env=env,check=True,timeout=10,capture_output=True)
    commands=[json.loads(line) for line in log.read_text().splitlines()]
    assert ['-m','alembic','upgrade','head'] in commands
    assert ['-m','gunicorn','-c','gunicorn.conf.py','src.api.app:app'] in commands
    assert all(args != ['-m','src.worker'] for args in commands)
    assert ['run','dev'] in commands
    assert all('scripts.train' not in ' '.join(args) and 'generate_dataset' not in ' '.join(args) for args in commands)
