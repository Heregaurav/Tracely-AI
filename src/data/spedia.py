"""SPEDIA v2 inspection and causal user-hour features from verified source fields."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from .integrity import atomic_json, sha256_file, utcnow

OFFICIAL_URL="https://zenodo.org/records/15525713"
OFFICIAL_MD5="e01e0baaf3b523a0b493fc9c52af2b1c"
EXCLUDED=("id","Agent_name","User","Timestamp","Decoder_name","Description","Full_log","Content","Level","Anomaly")
ACTIVITIES=("command","file","session","http","email","device")
FEATURE_NAMES=["event_count","activity_diversity",*[name+"_events" for name in ACTIVITIES],
 "file_change_events","file_access_events","login_events","failed_login_events",
 "unique_hosts","unique_commands","unique_resources","unique_email_recipients",
 "email_attachments_sum","email_size_sum_native","file_change_magnitude_native",
 "new_activity_types","new_hosts","new_commands","new_resources",
 "prior_events_mean_7d","prior_events_std_7d","volume_deviation","prior_observed_windows_7d",
 "hours_since_previous","active_span_seconds","interevent_std_seconds"]
COMMON_FEATURE_NAMES=["event_count","activity_diversity","file_events","session_events","http_events","email_events","device_events",
 "unique_hosts","prior_events_mean_7d","prior_events_std_7d","volume_deviation","prior_observed_windows_7d","hours_since_previous"]
FEATURE_VERSION="spedia-hour-v1"

def contract(common=False):
    names=COMMON_FEATURE_NAMES if common else FEATURE_NAMES
    return {"version":"spedia-cert-common-hour-v1" if common else FEATURE_VERSION,"family":"spedia",
            "scoring_unit":"user-nonoverlapping-hour","window_seconds":3600,"windows_per_day":24,
            "features":[{"name":n,"dtype":"float64","training":True,"inference":True,
                         "missing":"zero only for absent applicable events; no missing user imputation",
                         "source":"observed SPEDIA event fields; raw identifiers and annotations excluded",
                         "window":"past [t-7days,t) for prior_* and deviations; current closed hour for counts"} for n in names],
            "excluded_predictors":list(EXCLUDED),
            "common_scope":"file/session/http/email/device events only; command telemetry excluded before aggregation" if common else None}


def load_spedia(path):
    path=Path(path)
    df=pd.read_csv(path,low_memory=False)
    required={"id","Agent_name","User","Timestamp","Decoder_name","Activity","Action","Anomaly"}
    if not required.issubset(df): raise ValueError(f"Missing SPEDIA columns: {required-set(df)}")
    if not df.Anomaly.isin([0,1]).all(): raise ValueError("Anomaly must be a complete binary annotation")
    df["time"]=pd.to_datetime(df.Timestamp,format="mixed",errors="coerce")
    if df.time.isna().any(): raise ValueError("Invalid source timestamps; inspect before training")
    df["source_record_id"]=df.id.astype(str)
    df["scenario_proxy"]=df.Agent_name.str.extract(r"_([a-f0-9]{40})$",expand=False)
    df["simulation_marker"]=df.Agent_name.str.endswith("_simulation",na=False)
    df["cert_tag"]=df.Decoder_name.eq("cert")
    df["host"]=df.Agent_name.str.replace(r"_(?:simulation|[a-f0-9]{40})$","",regex=True)
    df["user"]=df.User.astype("string").str.strip().replace("",pd.NA)
    return df


def inspect_spedia(path,output="data/spedia/analysis",docs_path="docs/DATASET_ANALYSIS.md"):
    started=time.perf_counter(); path=Path(path); output=Path(output);output.mkdir(parents=True,exist_ok=True)
    frame=load_spedia(path)
    source_columns=list(pd.read_csv(path,nrows=0).columns)
    digest=hashlib.md5(path.read_bytes()).hexdigest()
    raw=frame[source_columns]
    quality={"dataset_id":"spedia-v2","source_url":OFFICIAL_URL,"source_path":str(path.resolve()),
       "sha256":sha256_file(path),"md5":digest,"official_md5_match":digest==OFFICIAL_MD5,
       "records":len(frame),"columns":{c:str(raw[c].dtype) for c in source_columns},
       "missing_values":raw.isna().sum().astype(int).to_dict(),"duplicate_rows":int(raw.duplicated().sum()),
       "duplicates_excluding_id":int(raw.drop(columns="id").duplicated().sum()),
       "unique_users":int(frame.user.nunique()),"missing_user_records":int(frame.user.isna().sum()),
       "label_counts":{str(k):int(v) for k,v in frame.Anomaly.value_counts().items()},
       "activity_counts":frame.Activity.value_counts().astype(int).to_dict(),
       "action_counts":frame.Action.value_counts().astype(int).to_dict(),
       "decoder_counts":frame.Decoder_name.value_counts().astype(int).to_dict(),
       "origin_label_counts":frame.groupby(["cert_tag","simulation_marker","Anomaly"]).size().rename("records").reset_index().to_dict("records"),
       "user_activity":frame.groupby(["user","Activity"],dropna=False).size().rename("events").reset_index().astype({"user":"string"}).fillna("<missing>").to_dict("records"),
       "time_min":str(frame.time.min()),"time_max":str(frame.time.max()),"observations":"individual events",
       "timezone":"not supplied; source wall-clock timestamps retained without inventing a timezone",
       "scenario_proxy_groups":int(frame.scenario_proxy.nunique()),
       "source_origin_limitations":["Decoder_name=cert is an explicit CERT-related tag; original CERT release/record IDs are not supplied.",
          "The simulation agent suffix exactly determines the target in this CSV; raw agent/source flags are excluded as predictors.",
          "Non-simulation rows include CERT-tagged rows; they cannot all be described as real participant activity.",
          "Hashed agent suffixes are grouping proxies, not verified attack-scenario IDs."],
       "created_at":utcnow(),"inspection_seconds":time.perf_counter()-started}
    atomic_json(output/"quality.json",quality)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi":130,"axes.spines.top":False,"axes.spines.right":False})
    def save(name):
        plt.tight_layout();plt.savefig(output/(name+".png"));plt.close()
    plt.figure(figsize=(6,4));frame.Anomaly.value_counts().sort_index().rename(index={0:"Annotated non-attack",1:"Annotated attack"}).plot.bar(color=["#3884a8","#cd6359"]);plt.ylabel("Events");save("labels")
    plt.figure(figsize=(7,4));frame.Activity.value_counts().plot.bar(color="#3884a8");plt.ylabel("Events");save("activities")
    plt.figure(figsize=(9,4));frame.user.value_counts().plot.bar(color="#3884a8");plt.ylabel("Events");save("users")
    plt.figure(figsize=(10,4));pd.crosstab(frame.time.dt.floor("d"),frame.Anomaly).rename(columns={0:"Annotated non-attack",1:"Annotated attack"}).plot(ax=plt.gca());plt.ylabel("Events/day");save("events_over_time")
    plt.figure(figsize=(10,5));raw.isna().mean().sort_values().plot.bar(color="#7a70aa");plt.ylabel("Missing fraction");save("missingness")
    numeric=raw.select_dtypes(include=np.number).drop(columns="Anomaly")
    corr=numeric.corr();plt.figure(figsize=(7,6));plt.imshow(corr,vmin=-1,vmax=1,cmap="RdBu_r");plt.colorbar(label="Pearson correlation (pairwise observed)");plt.xticks(range(len(corr)),corr.columns,rotation=70,ha="right");plt.yticks(range(len(corr)),corr.columns);save("numeric_correlation")
    text=f"""# SPEDIA v2 dataset analysis\n\nSource: {OFFICIAL_URL}. Local file: `{path}`.\n\nOfficial file MD5 match: **{quality['official_md5_match']}**. SHA-256: `{quality['sha256']}`.\n\nThere are **{len(frame):,} individual events**, **{len(source_columns)} columns**, **{quality['unique_users']} nonmissing user identifiers** and **{quality['missing_user_records']:,} events without a user**. Timestamps span {quality['time_min']} to {quality['time_max']}; timezone is unspecified. CSV row order is not chronological.\n\nLabels: {json.dumps(quality['label_counts'])}. Activities: {json.dumps(quality['activity_counts'])}. Full-row duplicates: {quality['duplicate_rows']}; duplicates ignoring the unique id: {quality['duplicates_excluding_id']}.\n\n## Leakage and provenance findings\n\nEvery `_simulation` agent row is label 0, and every other agent row is label 1. This is a perfect source/label shortcut. Descriptions contain suspiciousness annotations; severity Level and free text are excluded. Raw usernames, agent suffixes, decoder/source flags, IDs and timestamps are metadata, not learned identifiers. The remaining behavioral features can still reflect source-generation differences: excluding a direct shortcut does not remove the dataset's origin confounding.\n\n`Decoder_name=cert` marks {int(frame.cert_tag.sum()):,} records. It does not identify the original CERT release or original record identifiers. Non-simulation rows also include CERT-tagged records, so real-participant, simulated and CERT origins cannot be fully separated with confidence. No independent-CERT generalization claim is supported by these tags alone.\n\nHashed agent suffixes provide {quality['scenario_proxy_groups']} grouping proxies shared across host names. They are not documented scenario/session ground truth. Repeated users, reused event payloads and these suffixes can correlate records; the ML split report records purging and remaining limitations.\n\nThe controlled, relatively balanced event labels do not represent enterprise attack prevalence. Window-level prevalence will differ after aggregation. An event count is not a user-window count.\n\n## Columns and missing values\n\n| Column | dtype | Missing |\n|---|---|---|\n"""
    text+="\n".join(f"| {c} | {quality['columns'][c]} | {quality['missing_values'][c]} |" for c in source_columns)
    text+="\n\n## Figures\n\n"+"\n".join(f"- `{output/name}.png`" for name in ("labels","activities","users","events_over_time","missingness","numeric_correlation"))
    text+="\n\nMachine-readable counts, per-user activity and origin cross-tabs: `"+str(output/"quality.json")+"`. Raw CSV bytes are retained unchanged and ignored by Git.\n"
    Path(docs_path).write_text(text)
    return quality


def prepare_events(frame,strategy="temporal",seed=42):
    frame=frame.copy()
    source_cols=[c for c in frame if c not in ("id","time","source_record_id","scenario_proxy","simulation_marker","cert_tag","host","user")]
    # Same event with another UUID is not an independent observation.
    duplicate=frame.duplicated(subset=source_cols,keep="first")
    audit={"input_events":len(frame),"logical_duplicate_events_removed":int(duplicate.sum()),"missing_user_events_excluded":int(frame.user.isna().sum())}
    frame=frame.loc[~duplicate & frame.user.notna()].copy()
    origin=frame.time.min().floor("d")
    days=sorted(frame.time.dt.floor("d").unique())
    if strategy=="temporal":
        if len(days)<5: raise ValueError("At least five observed days required")
        boundaries=(pd.Timestamp(days[int(len(days)*.6)]),pd.Timestamp(days[int(len(days)*.8)]))
        frame["split"]=np.where(frame.time<boundaries[0],"train",np.where(frame.time<boundaries[1],"validation","test"))
        audit["boundaries"]=[str(t) for t in boundaries]
    elif strategy=="user_disjoint":
        splitter=GroupShuffleSplit(n_splits=1,train_size=.6,random_state=seed)
        train,rest=next(splitter.split(frame,groups=frame.user))
        val_idx,test_idx=next(GroupShuffleSplit(n_splits=1,train_size=.5,random_state=seed).split(frame.iloc[rest],groups=frame.iloc[rest].user))
        frame["split"]="train";frame.iloc[rest[val_idx],frame.columns.get_loc("split")]="validation";frame.iloc[rest[test_idx],frame.columns.get_loc("split")]="test"
    else: raise ValueError("Unsupported split strategy")
    crossing=frame.dropna(subset=["scenario_proxy"]).groupby("scenario_proxy").split.nunique()
    groups=set(crossing[crossing>1].index)
    purge=frame.scenario_proxy.isin(groups)
    audit["cross_split_scenario_proxy_groups_removed"]=sorted(groups)
    audit["scenario_proxy_events_purged"]=int(purge.sum())
    frame=frame.loc[~purge].copy()
    # Fingerprint payloads for overlap audits/purging, never as a model input.
    fingerprint_cols=[c for c in source_cols if c not in ("Timestamp","Anomaly","Description","Level","Agent_name")]+["host"]
    hashes=pd.util.hash_pandas_object(frame[fingerprint_cols].fillna("<missing>"),index=False).astype(str)
    frame["payload_hash"]=hashes
    ranks=frame.split.map({"train":0,"validation":1,"test":2})
    earliest=ranks.groupby(hashes).transform("min")
    repeated=ranks>earliest
    audit["evaluation_payload_duplicates_purged"]=int(repeated.sum())
    frame=frame.loc[~repeated].sort_values(["time","source_record_id"]).copy()
    frame["window_start"]=frame.time.dt.floor("h")
    frame["window_index"]=((frame.window_start-origin).dt.total_seconds()/3600).astype(int)
    audit.update(strategy=strategy,seed=seed,time_origin=str(origin),remaining_events=len(frame),
                 record_counts=frame.split.value_counts().to_dict(),
                 limitation="Scenario suffixes are proxies; unmarked activity sequences cannot be independently identified. User-disjoint evaluation is not globally time-disjoint." if strategy=="user_disjoint" else "Time-disjoint; users may recur. Known crossing scenario proxies and repeated evaluation payloads are purged.")
    return frame,audit


def aggregate_windows(events,*,common=False):
    if common: events=events.loc[events.Activity.isin(["file","session","http","email","device"])].copy()
    rows=[];relationships=[]
    for (user,start),group in events.groupby(["user","window_start"],sort=True):
        def unique(column): return set(group[column].dropna().astype(str)) if column in group else set()
        def numeric(column): return pd.to_numeric(group[column],errors="coerce") if column in group else pd.Series(dtype=float)
        types=unique("Activity");hosts=unique("host");commands=unique("Command")
        resources=unique("Path")|unique("Filename")
        recipients=set()
        for value in unique("To")|unique("Cc")|unique("Bcc"):
            recipients.update(x.strip() for x in value.split(";") if x.strip())
        seconds=group.time.astype("int64").to_numpy()/1e9
        delta=np.diff(np.sort(seconds))
        row={"user":str(user),"window_start":str(start),"window_index":int(group.window_index.iloc[0]),
             "label":bool(group.Anomaly.max()) if "Anomaly" in group and group.Anomaly.notna().any() else None,"attack_event_count":int(group.Anomaly.sum()) if "Anomaly" in group and group.Anomaly.notna().any() else None,
             "record_ids":group.source_record_id.tolist(),"split":group.split.iloc[0],
             "event_count":float(len(group)),"activity_diversity":float(len(types)),
             **{name+"_events":float(group.Activity.eq(name).sum()) for name in ACTIVITIES},
             "file_change_events":float(group.Action.isin(["File modified","File added","File deleted"]).sum()),
             "file_access_events":float(group.Action.eq("File accessed").sum()),
             "login_events":float(group.Action.eq("Login").sum()),
             "failed_login_events":float(group.Action.isin(["Login Failed","Multiple failed logins"]).sum()),
             "unique_hosts":float(len(hosts)),"unique_commands":float(len(commands)),"unique_resources":float(len(resources)),
             "unique_email_recipients":float(len(recipients)),"email_attachments_sum":float(numeric("Attachments").sum()),
             "email_size_sum_native":float(numeric("Size").sum()),
             "file_change_magnitude_native":float((numeric("Size_after")-numeric("Size_before")).abs().sum()),
             "active_span_seconds":float(seconds.max()-seconds.min()),"interevent_std_seconds":float(delta.std()) if len(delta) else 0.,
             "_types":types,"_hosts":hosts,"_commands":commands,"_resources":resources}
        rows.append(row)
        for host,count in group.host.value_counts().items():
            relationships.append({"user":str(user),"window_index":row["window_index"],"host":host,"weight":int(count)})
    table=pd.DataFrame(rows).sort_values(["user","window_index"]).reset_index(drop=True)
    if table.empty: raise ValueError("No attributable user windows available")
    for _,indices in table.groupby("user",sort=False).groups.items():
        seen={k:set() for k in ("types","hosts","commands","resources")};history=[];previous=None
        for i in indices:
            row=table.loc[i];index=int(row.window_index)
            past=[r for r in history if index-168<=r[0]<index]
            values=[r[1] for r in past];mean=float(np.mean(values)) if values else 0.;std=float(np.std(values)) if values else 0.
            for kind,feature in (("types","new_activity_types"),("hosts","new_hosts"),("commands","new_commands"),("resources","new_resources")):
                current=row["_"+kind];table.loc[i,feature]=len(current-seen[kind]);seen[kind].update(current)
            table.loc[i,"prior_events_mean_7d"]=mean;table.loc[i,"prior_events_std_7d"]=std
            table.loc[i,"volume_deviation"]=(row.event_count-mean)/max(std,1) if values else 0.
            table.loc[i,"prior_observed_windows_7d"]=len(values)
            table.loc[i,"hours_since_previous"]=index-previous if previous is not None else 0
            history.append((index,row.event_count));previous=index
    table=table.drop(columns=[c for c in table if c.startswith("_")])
    names=COMMON_FEATURE_NAMES if common else FEATURE_NAMES
    table[names]=table[names].astype(float)
    # Window vectors reused across partitions can encode duplicate sequences.
    hashes=pd.util.hash_pandas_object(table[names],index=False).astype(str)
    ranks=table.split.map({"train":0,"validation":1,"test":2}).fillna(0)
    keep=ranks==ranks.groupby(hashes).transform("min")
    purged=int((~keep).sum());table=table.loc[keep].copy()
    table["window_id"]=[hashlib.sha256((r.user+"|"+r.window_start+"|"+"|".join(r.record_ids)).encode()).hexdigest() for r in table.itertuples()]
    valid={(r.user,r.window_index) for r in table.itertuples()}
    edges=pd.DataFrame([r for r in relationships if (r["user"],r["window_index"]) in valid])
    return table.sort_values(["window_index","user"]).reset_index(drop=True),edges,purged


def build_spedia(path,output,*,strategy="temporal",common=False,seed=42):
    started=time.perf_counter();output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if (output/"features.json").exists(): raise FileExistsError("Use a new immutable SPEDIA feature output directory")
    frame=load_spedia(path);events,audit=prepare_events(frame,strategy,seed)
    table,edges,purged=aggregate_windows(events,common=common)
    definition=contract(common)
    dataset_id="spedia-v2"+("-common" if common else "")+("-user-disjoint" if strategy=="user_disjoint" else "")
    table["dataset_id"]=dataset_id
    table.to_parquet(output/"features.parquet",index=False);edges.to_parquet(output/"relationships.parquet",index=False)
    split_manifest={name:{"window_ids":g.window_id.tolist(),"record_ids":[x for ids in g.record_ids for x in ids],
        "users":sorted(g.user.unique().tolist()),"min_time":g.window_start.min(),"max_time":g.window_start.max(),
        "windows":len(g),"events":int(g.event_count.sum()),"attack_windows":int(g.label.sum()),"attack_events":int(g.attack_event_count.sum())}
        for name,g in table.groupby("split")}
    if set(split_manifest)!={"train","validation","test"}:raise ValueError("Split purging left an empty period; no model may be trained")
    atomic_json(output/"split_manifest.json",{"policy":audit,"splits":split_manifest,"feature_duplicate_windows_purged":purged})
    md5=hashlib.md5(Path(path).read_bytes()).hexdigest()
    provenance={"source_url":OFFICIAL_URL,"filename":Path(path).name,"sha256":sha256_file(path),"md5":md5,
                "official_md5_match":md5==OFFICIAL_MD5,"registered_at":utcnow(),"authenticity":"publisher-MD5-verified" if md5==OFFICIAL_MD5 else "unverified-source-or-unit-fixture",
                "dataset_version":"SPEDIA-v2","source_origins":"mixed participant exercise, simulation, and CERT-derived records; incomplete row-origin provenance",
                "dataset_records":len(frame)}
    report={"dataset_id":dataset_id,"family":"spedia","is_fixture":md5!=OFFICIAL_MD5,"contract":definition,"feature_version":definition["version"],
            "rows":len(table),"provenance":provenance,"window_unit":"hour","relative_time":False,"time_origin":audit["time_origin"],
            "features_sha256":sha256_file(output/"features.parquet"),"relationships_path":str((output/"relationships.parquet").resolve()),
            "relationships_sha256":sha256_file(output/"relationships.parquet"),"split_manifest_path":str((output/"split_manifest.json").resolve()),
            "split_audit":audit,"feature_duplicates_purged":purged,"preprocessing_seconds":time.perf_counter()-started,
            "analyzed_event_count":int(table.event_count.sum()),"selection_policy":{"split_strategy":strategy,"scope":"nonoverlapping user-hours; current-hour end scoring","common":common},
            "labels":{"available":True,"meaning":"Anomaly=1 source annotation, user-hour label is any attack event","coverage":"Only nonmissing-user events retained after declared deduplication and group purging"}}
    atomic_json(output/"features.json",report)
    return report
