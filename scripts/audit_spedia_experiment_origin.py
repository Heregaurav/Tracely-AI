"""Development-only source/telemetry controls; no test evaluation or tuning."""
import json
from pathlib import Path
import pandas as pd
from src.data.spedia import load_spedia
from src.data.integrity import atomic_json

if __name__=='__main__':
    root=Path('data/spedia/experiment-v5')
    frame=pd.read_parquet(root/'development_features.parquet')
    mapping={rid:r.split for r in frame.itertuples() for rid in r.record_ids}
    raw=load_spedia('logs_SPEDIA_annotated_en.csv')
    events=raw.loc[raw.source_record_id.isin(mapping)].copy()
    events['split']=events.source_record_id.map(mapping)
    events['command_present']=events.Command.notna()
    table=events.groupby(['split','simulation_marker','Anomaly']).agg(events=('id','size'),commands_present=('command_present','sum')).reset_index()
    activity=events.groupby(['split','simulation_marker','Activity']).size().rename('events').reset_index()
    atomic_json(root/'origin_audit.json',dict(scope='Training/validation only; diagnostic controls, not proof of robustness.',
        source_label=table.to_dict('records'),activity=activity.to_dict('records'),
        direct_origin_rule_accuracy=float((~events.simulation_marker==events.Anomaly.astype(bool)).mean()),
        within_origin_discrimination='Undefined: every origin-marker stratum contains one label only.',
        caution='Normal validation has no command telemetry. Command rarity can be a source shortcut even with training-normal dictionaries. Source-reduced ablation does not eliminate temporal/volume shortcuts.'))
    print(table.to_string(index=False))
