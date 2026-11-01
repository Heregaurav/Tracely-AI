"""Export every retained held-out hour in chronology, without outcome selection."""
import argparse
import json
from pathlib import Path
import pandas as pd
from src.data.spedia import load_spedia
from src.data.integrity import atomic_json, sha256_file


def export(source, frozen, review, output):
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    base=json.loads((Path(review)/'replay_manifest.json').read_text())
    scored=pd.read_parquet(Path(frozen)/'scores.parquet')
    selected=scored.loc[scored.split=='test'].sort_values(['window_start','user'])
    import joblib
    model=joblib.load(Path(frozen)/'model.joblib')
    inputs=selected[['window_id','user','window_start','window_index','record_ids',*model.names]]
    inputs.to_parquet(out/'replay_inputs.parquet',index=False)
    ids={rid for values in inputs.record_ids for rid in values}
    events=load_spedia(source)
    safe=['source_record_id','user','time','Activity','Action','host']
    events.loc[events.source_record_id.isin(ids),safe].sort_values(['time','source_record_id']).to_parquet(out/'replay_events.parquet',index=False)
    atomic_json(out/'replay_ground_truth.json',{'windows':[dict(window_id=r.window_id,label=bool(r.label),example_outcome=('TP' if r.label else 'FP') if r.risk_score>=model.threshold else ('FN' if r.label else 'TN')) for r in selected.itertuples()]})
    base.update(inputs_sha256=sha256_file(out/'replay_inputs.parquet'),events_sha256=sha256_file(out/'replay_events.parquet'),ground_truth_sha256=sha256_file(out/'replay_ground_truth.json'),
        events=len(ids),windows=len(inputs),window_ids=inputs.window_id.tolist(),mode='realistic',
        selection='All retained original held-out user-hours, ordered chronologically; no selection by label, score or outcome. Representative of the retained research test only. Purged/missing-user records and inactive hours are absent.',
        history='Historical SPEDIA activity, never live enterprise traffic. Exact original past-context feature vectors; predictions become available at hour closure. Event playback does not reconstruct the omitted history.')
    atomic_json(out/'replay_manifest.json',base)
    return dict(windows=len(inputs),events=len(ids))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='data/spedia/replay-realistic-v1');a=p.parse_args()
    print(export('logs_SPEDIA_annotated_en.csv','data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223','data/spedia/review-v3',a.output))
