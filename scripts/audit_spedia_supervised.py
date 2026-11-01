"""Validation-only, fixed-specification ablations. Never score the frozen test set."""
import argparse
import json
from pathlib import Path
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score,roc_auc_score
from sklearn.preprocessing import StandardScaler
import pandas as pd
from src.data.integrity import atomic_json, sha256_file


def audit(run,features,output):
    root=Path(run);path=Path(features);out=Path(output)
    if out.exists():raise FileExistsError('Preserve experiments: choose a new output directory')
    metadata=json.loads((root/'metrics.json').read_text());definition=json.loads(path.with_suffix('.json').read_text())
    if sha256_file(root/'model.joblib')!=metadata['artifact_sha256'] or sha256_file(path)!=definition['features_sha256']:raise ValueError('Checksum mismatch')
    frozen=joblib.load(root/'model.joblib');frame=pd.read_parquet(path)
    train=frame.loc[frame.split=='train'].copy();val=frame.loc[frame.split=='validation'].copy()
    variants={'all_permitted_features':frozen.names,
        'without_relationship_and_history_features':[n for n in frozen.names if not n.startswith(('unique_','new_','prior_','hours_','volume_'))],
        'activity_counts_only':['event_count','activity_diversity','command_events','file_events','session_events','http_events','email_events','device_events']}
    out.mkdir(parents=True)
    plan={'purpose':'Association sensitivity audit, not model selection or independent validation','variants':variants,'seed':42,
        'training_window_ids':train.window_id.tolist(),'validation_window_ids':val.window_id.tolist(),
        'source_features_sha256':sha256_file(path),'uses_test_records':False,
        'method':'Same logistic C=1 balanced class weights; normal-training-only scaler. Fixed subsets chosen by feature meaning, no threshold tuning; raw logistic ranking metrics only.'}
    atomic_json(out/'plan.json',plan)
    results={}
    for name,names in variants.items():
        scaler=StandardScaler().fit(train.loc[~train.label,names])
        model=LogisticRegression(C=1.,class_weight='balanced',max_iter=1000,random_state=42).fit(scaler.transform(train[names]),train.label)
        score=model.predict_proba(scaler.transform(val[names]))[:,1]
        results[name]={'validation_pr_ap':float(average_precision_score(val.label,score)),
           'validation_roc_auc':float(roc_auc_score(val.label,score)),'features':len(names)}
        joblib.dump({'scaler':scaler,'model':model,'feature_names':names},out/(name+'.joblib'))
    atomic_json(out/'results.json',{'results':results,'validation_positive':int(val.label.sum()),'validation_negative':int((~val.label).sum()),
        'warning':'Ablation associations cannot disentangle source generation from malicious intent. No held-out test scores, thresholds or deployed models changed.'})
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',default='data/artifacts/spedia-dcd995bcea1644cabd261b4bcc4dd223');p.add_argument('--features',default='data/spedia/features-temporal/features.parquet');p.add_argument('--output',required=True);a=p.parse_args();print(audit(a.run,a.features,a.output))
