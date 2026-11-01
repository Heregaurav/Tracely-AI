"""SPEDIA research models: frozen preprocessing, validation selection, untouched test."""
from __future__ import annotations
import copy
import json
import os
import platform
from pathlib import Path
import resource
import time
import uuid

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score,confusion_matrix,precision_recall_curve,roc_curve,
                             precision_score,recall_score,f1_score,roc_auc_score)
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from src.data.integrity import atomic_json, sha256_file, utcnow
from src.models.scoring import percentile_scores,combine


def metrics(y,index,threshold,k=20):
    y=np.asarray(y,dtype=bool);index=np.asarray(index,dtype=float);prediction=index>=threshold
    tn,fp,fn,tp=confusion_matrix(y,prediction,labels=[False,True]).ravel()
    order=np.argsort(-index,kind="stable")[:min(k,len(y))]
    both=len(np.unique(y))==2
    return {"windows":len(y),"positive_windows":int(y.sum()),"threshold":float(threshold),
            "precision":float(precision_score(y,prediction,zero_division=0)) if y.any() else None,
            "recall":float(recall_score(y,prediction,zero_division=0)) if y.any() else None,
            "f1":float(f1_score(y,prediction,zero_division=0)) if y.any() else None,
            "roc_auc":float(roc_auc_score(y,index)) if both else None,
            "pr_auc_average_precision":float(average_precision_score(y,index)) if both else None,
            "confusion_matrix":[[int(tn),int(fp)],[int(fn),int(tp)]],
            "false_positive_rate":float(fp/(fp+tn)) if fp+tn else None,
            "false_negative_rate":float(fn/(fn+tp)) if fn+tp else None,
            "precision_at_k":float(y[order].mean()) if len(order) else None,
            "recall_at_k":float(y[order].sum()/y.sum()) if y.any() else None,"k":len(order),
            "alert_count":int(prediction.sum()),"alerts_per_1000_windows":float(prediction.mean()*1000),
            "false_alerts_per_1000_windows":float(fp/len(y)*1000),
            "detection_delay":"Unsupported: no verified attack onset/session ground truth; end-of-hour scoring is retrospective."}


def choose_threshold(y,index):
    # Validation only. F1 objective is appropriate to this labeled controlled study,
    # not an assumed enterprise prevalence or calibrated malicious probability.
    if len(np.unique(y))<2:return 95.
    choices=np.unique(np.clip(np.r_[np.linspace(1,99,99),np.asarray(index)],1,99))
    values=np.asarray(index,dtype=float)
    labels=np.asarray(y,dtype=bool)
    order=np.argsort(values,kind="stable")
    sorted_values=values[order]
    cumulative_positive=np.r_[0,np.cumsum(labels[order],dtype=np.int64)]
    offsets=np.searchsorted(sorted_values,choices,side="left")
    predicted=len(values)-offsets
    true_positive=int(labels.sum())-cumulative_positive[offsets]
    false_positive=predicted-true_positive
    denominator=2*true_positive+false_positive+(int(labels.sum())-true_positive)
    f1=np.divide(2*true_positive,denominator,out=np.zeros_like(choices),where=denominator>0)
    best=np.flatnonzero(f1==f1.max())[-1]
    return float(choices[best])


class BehavioralDetector:
    def __init__(self,definition,*,estimators=200,epochs=100,seed=42,neural=True):
        self.contract=copy.deepcopy(definition)
        self.names=[item["name"] for item in definition["features"]]
        self.params={"estimators":estimators,"epochs":epochs,"seed":seed,"neural":neural}
        self.scaler=StandardScaler();self.references={};self.neural=None;self.supervised=None
        self.active="if_pca_60";self.threshold=85.

    def matrix(self,frame):
        if len(set(self.names))!=len(self.names) or set(self.names)-set(frame):raise ValueError("Missing/incompatible feature contract")
        values=frame.loc[:,self.names].to_numpy(dtype=float)
        if not np.isfinite(values).all():raise ValueError("Nonfinite behavioral features")
        return values

    def graph(self,frame):
        if not {"new_hosts","unique_hosts","prior_observed_windows_7d"}.issubset(frame):return None
        return np.where(frame.prior_observed_windows_7d>0,frame.new_hosts/np.maximum(frame.unique_hosts,1),0.)

    def raw(self,frame):
        x=self.scaler.transform(self.matrix(frame))
        result={"if":-self.forest.score_samples(x),"pca":np.mean((x-self.pca.inverse_transform(self.pca.transform(x)))**2,axis=1)}
        if self.neural is not None:result["neural"]=np.mean((x-self.neural.predict(x))**2,axis=1)
        if self.supervised is not None:result["supervised"]=self.supervised.predict_proba(x)[:,1]
        graph=self.graph(frame)
        if graph is not None:result["graph"]=graph
        return result

    def components(self,frame):
        return {name:percentile_scores(values,self.references[name]) for name,values in self.raw(frame).items()}

    def configurations(self):
        result={"if":{"if":1.},"pca":{"pca":1.}}
        if self.neural is not None:result["neural"]={"neural":1.}
        for reconstruction in ["pca",*(["neural"] if self.neural is not None else [])]:
            for weight in (.25,.5,.6,.75):
                result[f"if_{reconstruction}_{int(weight*100)}"]={"if":weight,reconstruction:1-weight}
            if "graph" in self.references:
                result[f"if_{reconstruction}_graph"]={"if":.6,reconstruction:.3,"graph":.1}
        if self.supervised is not None:result["supervised_logistic"]={"supervised":1.}
        return result

    def fit(self,train,validation):
        normal=train.loc[~train.label];reference=validation.loc[~validation.label]
        if len(normal)<3 or len(reference)<2:raise ValueError("Insufficient designated normal train/validation windows")
        x=self.scaler.fit_transform(self.matrix(normal));xv=self.scaler.transform(self.matrix(reference))
        self.forest=IsolationForest(n_estimators=self.params["estimators"],random_state=self.params["seed"],n_jobs=1,contamination="auto").fit(x)
        self.pca=PCA(n_components=max(1,min(x.shape[0]-1,x.shape[1]//2)),random_state=self.params["seed"]).fit(x)
        self.neural_history=[]
        if self.params["neural"]:
            network=MLPRegressor(hidden_layer_sizes=(24,8,24),activation="relu",alpha=.001,random_state=self.params["seed"],
                                 batch_size=min(64,len(x)),shuffle=False,learning_rate_init=.001)
            best=float("inf");patience=0
            for epoch in range(self.params["epochs"]):
                network.partial_fit(x,x)
                loss=float(np.mean((network.predict(xv)-xv)**2))
                self.neural_history.append({"epoch":epoch+1,"normal_validation_mse":loss})
                if np.isfinite(loss) and loss<best-1e-6:
                    best=loss;patience=0;self.neural=copy.deepcopy(network)
                else:patience+=1
                if patience>=8:break
            if self.neural is None:raise ValueError("No finite neural reconstruction checkpoint")
        if train.label.nunique()==2:
            self.supervised=LogisticRegression(C=1.,class_weight="balanced",max_iter=1000,random_state=self.params["seed"]).fit(
                self.scaler.transform(self.matrix(train)),train.label)
        self.references={name:np.sort(values) for name,values in self.raw(reference).items()}
        components=self.components(validation)
        self.validation_metrics={};self.thresholds={}
        for name,weights in self.configurations().items():
            score=combine({k:components[k] for k in weights},weights)
            threshold=choose_threshold(validation.label,score)
            self.thresholds[name]=threshold
            self.validation_metrics[name]=metrics(validation.label,score,threshold)
        # Predeclared operational family is unsupervised UEBA. Supervised learning
        # is an explicitly separate assumption/benchmark, not silently substituted.
        eligible=[name for name in self.configurations() if not name.startswith("supervised")]
        if validation.label.nunique()==2:
            self.active=max(eligible,key=lambda n:(self.validation_metrics[n]["pr_auc_average_precision"],self.validation_metrics[n]["f1"],-len(self.configurations()[n])))
        self.threshold=self.thresholds[self.active]
        high=self.threshold
        self.tier_thresholds=[.4*high,.8*high,high,(high+100)/2]
        return self

    def score(self,frame):
        components=self.components(frame);weights=self.configurations()[self.active]
        index=combine({k:components[k] for k in weights},weights)
        tiers=np.asarray(["NORMAL","LOW","MEDIUM","HIGH","CRITICAL"])[np.searchsorted(self.tier_thresholds,index,side="right")]
        return index,tiers,components


def train_spedia(feature_path,artifacts,*,estimators=200,epochs=100,neural=True):
    started=time.perf_counter();feature_path=Path(feature_path);root=Path(artifacts)
    report=json.loads(feature_path.with_suffix(".json").read_text())
    if report.get("family")!="spedia" or sha256_file(feature_path)!=report["features_sha256"]:raise ValueError("SPEDIA feature provenance/contract mismatch")
    frame=pd.read_parquet(feature_path).sort_values(["window_index","user"]).reset_index(drop=True)
    partitions={name:frame.loc[frame.split==name].copy() for name in ("train","validation","test")}
    model=BehavioralDetector(report["contract"],estimators=estimators,epochs=epochs,neural=neural)
    model.fit(partitions["train"],partitions["validation"])
    training_seconds=time.perf_counter()-started
    # Frozen model choice, scaler, references and thresholds precede all test use.
    test=partitions["test"];components=model.components(test)
    evaluated={name:metrics(test.label,combine({k:components[k] for k in weights},weights),model.thresholds[name]) for name,weights in model.configurations().items()}
    version=("fixture-spedia-" if report["is_fixture"] else "spedia-")+uuid.uuid4().hex
    root.mkdir(parents=True,exist_ok=True);stage=root/("."+version);stage.mkdir()
    joblib.dump(model,stage/"model.joblib")
    restored=joblib.load(stage/"model.joblib")
    np.testing.assert_allclose(model.score(test)[0],restored.score(test)[0])
    score,tiers,all_components=model.score(frame)
    scored=frame.copy();scored["model_version"]=version;scored["risk_score"]=score;scored["risk_tier"]=tiers
    for name,values in all_components.items():scored[name+"_score"]=values
    scored["explanation"]=[json.dumps({"kind":"behavioral comparisons; not exact model attribution","window_start":r.window_start,
       "window_index":int(r.window_index),"relative_day":int(r.window_index)//24,"window_unit":"hour",
       "event_count":float(r.event_count),"prior_7d_observed_window_mean":float(r.prior_events_mean_7d),
       "volume_deviation":float(r.volume_deviation),"new_hosts":float(getattr(r,"new_hosts",0)),
       "history_windows":float(r.prior_observed_windows_7d),"evidence_record_ids":list(r.record_ids)[:5],
       "component_indices":{k:float(v[i]) for k,v in all_components.items()},
       "limitation":"Controlled mixed-origin SPEDIA annotations; source-generation confounding remains. Anomaly indices do not prove employee intent."}) for i,r in enumerate(frame.itertuples())]
    scored.to_parquet(stage/"scores.parquet",index=False)
    benchmark=[]
    for size in (1,32,256):
        batch=test.iloc[:size];durations=[]
        for _ in range(5):
            begin=time.perf_counter();model.score(batch);durations.append(time.perf_counter()-begin)
        elapsed=float(np.median(durations));benchmark.append({"requested_batch_size":size,"actual_batch_size":len(batch),"median_batch_seconds":elapsed,"seconds_per_record":elapsed/len(batch),"records_per_second":len(batch)/elapsed})
    manifest=json.loads(Path(report["split_manifest_path"]).read_text())
    split_summary={name:{k:v for k,v in details.items() if k not in ("record_ids","window_ids")} for name,details in manifest["splits"].items()}
    metadata={"version":version,"created_at":utcnow(),"is_fixture":report["is_fixture"],"family":"spedia","dataset":report,
       "evaluation_scope":"UNIT TEST FIXTURE ONLY" if report["is_fixture"] else "Publisher-checksum-verified SPEDIA v2 controlled mixed-origin research dataset",
       "active_configuration":model.active,"weights":model.configurations()[model.active],"models":{"reconstruction":"PCA baseline","neural":"genuine dense MLP autoencoder (24,8,24)" if model.neural else "not trained","supervised":"separate logistic regression benchmark" if model.supervised is not None else "not trained: training partition has one class"},
       "parameters":model.params,"contract":report["contract"],"window_unit":"hour","relative_time":False,
       "split_policy":report["split_audit"],"splits":split_summary,"split_manifest_path":report["split_manifest_path"],
       "scaling":"StandardScaler fitted only on annotated non-attack training user-hours. No identifiers, annotation text, origin markers or test statistics.",
       "calibration":{"policy_version":"spedia-validation-v1","component_scale":"saved validation-normal empirical midrank percentile","reference":"annotated non-attack validation user-hours","tier_thresholds":model.tier_thresholds,"high_threshold":model.threshold,"threshold_objective":"maximum validation F1; ties favor higher threshold","index_is_probability":False},
       "selection_policy":"Choose unsupervised candidate by validation AP, then validation F1, then simpler weights. Weight grid 25/50/60/75 percent IF. Supervised logistic is a separate labeled-training benchmark, not an operational replacement. Test set never selects the model.",
       "validation_metrics":model.validation_metrics,"held_out_metrics":evaluated,"neural_training":model.neural_history,
       "benchmark":{"scope":"model-only user-hour scoring; not API latency","training_seconds":training_seconds,"batches":benchmark,
            "peak_process_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=="Darwin" else 1024),
            "environment":{"platform":platform.platform(),"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,"sklearn":sklearn.__version__,"logical_cpus":os.cpu_count()}},
       "artifact_sha256":sha256_file(stage/"model.joblib"),"scores_sha256":sha256_file(stage/"scores.parquet"),
       "external_evaluation":{"CERT":"not executed; official records absent and source overlap unresolved"},
       "limitations":["Mixed exercise/simulation/CERT origins confound labels; raw agent simulation marker exactly predicts labels and is excluded.","Origin/source proxies may remain in behavioral distributions.","Scenario suffixes are proxies; unmarked correlated sequences cannot be certified independent.","Balanced research data does not establish enterprise precision or attack prevalence.","Source timestamps have no supplied timezone.","Detection delay unsupported without verified attack onset metadata."]}
    atomic_json(stage/"metrics.json",metadata)
    atomic_json(stage/"split_manifest.json",manifest)
    # Error analysis uses the already evaluated frozen model, never retunes it.
    active_scores=model.score(test)[0];prediction=active_scores>=model.threshold
    errors=test.loc[prediction!=test.label].copy();errors["predicted_attack"]=prediction[prediction!=test.label]
    errors[["window_id","user","window_start","label","predicted_attack","record_ids"]].head(30).to_json(stage/"error_analysis.json",orient="records",indent=2)
    _plots(stage,test,components,model)
    text=f"# SPEDIA model comparison: {version}\n\nScope: {metadata['evaluation_scope']}\n\nSelected on validation only: **{model.active}**, high threshold {model.threshold:.3f}.\n\n"
    text+="| Model | Test precision | Recall | F1 | PR-AP | ROC-AUC | False alerts/1000 windows |\n|---|---|---|---|---|---|---|\n"
    for name,m in evaluated.items():text+=f"| {name} | {m['precision']} | {m['recall']} | {m['f1']} | {m['pr_auc_average_precision']} | {m['roc_auc']} | {m['false_alerts_per_1000_windows']} |\n"
    text+="\nSupervised logistic uses labeled training windows; other candidates fit designated normal training windows only. These are user-hour metrics, not event or employee-level accuracy.\n\n"+"\n".join("- "+x for x in metadata["limitations"])+"\n"
    (stage/"REPORT.md").write_text(text);stage.rename(root/version)
    return metadata


def _plots(root,test,components,model):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    score=model.score(test)[0];cm=confusion_matrix(test.label,score>=model.threshold,labels=[False,True])
    fig,ax=plt.subplots(figsize=(5,4));ax.imshow(cm,cmap="Blues");ax.set(xticks=[0,1],yticks=[0,1],xlabel="Predicted user-hour label",ylabel="Annotated user-hour label")
    for i in range(2):
        for j in range(2):ax.text(j,i,str(cm[i,j]),ha="center",va="center")
    fig.tight_layout();fig.savefig(root/"confusion_matrix.png",dpi=140);plt.close(fig)
    if test.label.nunique()!=2:return
    for kind in ("roc","precision_recall"):
        fig,ax=plt.subplots(figsize=(7,5))
        for name,weights in model.configurations().items():
            if name not in ("if","pca","neural","supervised_logistic",model.active):continue
            values=combine({k:components[k] for k in weights},weights)
            if kind=="roc":x,y,_=roc_curve(test.label,values)
            else:y,x,_=precision_recall_curve(test.label,values)
            ax.plot(x,y,label=name)
        ax.set(xlabel="False-positive rate" if kind=="roc" else "Recall",ylabel="True-positive rate" if kind=="roc" else "Precision")
        ax.legend();fig.tight_layout();fig.savefig(root/(kind+".png"),dpi=140);plt.close(fig)
