"""Read-only repeated replay-compute benchmark, separate from database and browser."""
import argparse
import json
from pathlib import Path
import statistics
import time
import joblib
import numpy as np
from src.data.integrity import atomic_json, sha256_file
from src.db.replay import load_replay

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repeats',type=int,default=5);p.add_argument('--output',required=True);a=p.parse_args()
    if a.repeats<1:p.error('repeats must be positive')
    if Path(a.output).exists():raise FileExistsError('Choose a new benchmark output path')
    rows=[]
    for _ in range(a.repeats):
        timings={}
        def timed(name,operation):
            start=time.perf_counter();result=operation();timings[name]=(time.perf_counter()-start)*1000;return result
        manifest,frame=timed('input_integrity_and_parquet_ms',lambda:load_replay('data/spedia/replay-realistic-v1'))
        artifact=Path(manifest['model_directory'])/'model.joblib'
        timed('artifact_sha256_ms',lambda:sha256_file(artifact))
        model=timed('joblib_deserialize_ms',lambda:joblib.load(artifact))
        before=timed('pre_inference_mutation_hash_ms',lambda:joblib.hash(model))
        scores=timed('inference_ms',lambda:model.score(frame[model.names])[0])
        after=timed('post_inference_mutation_hash_ms',lambda:joblib.hash(model))
        assert before==after and np.isfinite(scores).all()
        rows.append(timings)
    report=dict(context='Read-only local process, warm filesystem caches possible, no DB or browser. Same complete retained replay; no fits.',windows=len(frame),events=manifest['events'],repeats=rows,median_ms={k:statistics.median(row[k] for row in rows) for k in rows[0]})
    atomic_json(a.output,report);print(json.dumps(report['median_ms'],indent=2))
