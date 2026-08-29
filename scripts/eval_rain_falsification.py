#!/usr/bin/env python3
"""Same places, same labels, another storm's rain field.

Every radar file was collected against the same point list, so storm B's rain
can be read at storm A's points exactly. If A's floods are still found once
they are paired with B's weather, the model was never using the weather.
"""
import json, sys, importlib.util, numpy as np, pandas as pd
from pathlib import Path
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

spec=importlib.util.spec_from_file_location("bett","scripts/build_event_training_table.py")
bett=importlib.util.module_from_spec(spec); spec.loader.exec_module(bett)

SP = "config/radar"
anchors={k:v for k,v in json.load(open(f"{SP}/flood_hours.json")).items() if v is not None}

TERRAIN=["elevation","rel_200m","rel_500m","rel_1000m","rel_2000m","slope_deg","above_river"]
RAIN=["rain_1h","rain_3h","rain_6h","rain_12h","rain_24h"]
d=pd.read_csv("data/processed/ml/training/event_rain_terrain.csv").dropna(subset=TERRAIN+RAIN)
d=d[~d.event.astype(str).isin(["20220814","20230715"])].copy()
d["key"]=d.lon.round(5).astype(str)+"_"+d.lat.round(5).astype(str)

# rain totals per event, keyed by point
store={}
for p in sorted(Path("data/interim/radar/events").glob("rain_*.npz")):
    ev=p.stem.replace("rain_","")
    z=np.load(p)
    if "lon" not in z: continue
    spans=z["span_min"].astype("float64") if "span_min" in z else np.full(z["series"].shape[0],float(z["step_min"]))
    series=z["series"]; end=len(spans)
    if ev in anchors:
        cut=bett.first_after(z["stamps"],ev,anchors[ev])
        if cut is not None and cut>=2: end=cut
    tot=bett.accumulate(series[:end],spans[:end],forward=False)
    keys=np.char.add(np.char.add(np.round(z["lon"],5).astype(str),"_"),
                     np.round(z["lat"],5).astype(str))
    store[ev]={"idx":{k:i for i,k in enumerate(keys)},"tot":tot}

events=sorted(d.event.astype(str).unique())
partner={e:events[(i+3)%len(events)] for i,e in enumerate(events)}

rows=[]
for e in events:
    a=d[d.event.astype(str)==e].copy(); b=store[partner[e]]
    pos=np.array([b["idx"].get(k,-1) for k in a.key])
    keep=pos>=0
    a=a[keep]; pos=pos[keep]
    for h,c in zip((1,3,6,12,24),RAIN):
        a[c]=b["tot"][h][pos]
    rows.append(a)
s=pd.concat(rows).dropna(subset=RAIN)
print(f"바꿔치기 완료: {len(s):,}행 (원본 {len(d):,}행), 양성 {int(s.flooded.sum()):,}\n")

def fit(tr,te,cols):
    p=max(int(tr.flooded.sum()),1)
    m=XGBClassifier(n_estimators=400,max_depth=5,learning_rate=0.05,subsample=0.8,
      colsample_bytree=0.8,min_child_weight=5,reg_lambda=2.0,eval_metric="logloss",
      n_jobs=8,scale_pos_weight=(len(tr)-p)/p)
    m.fit(tr[cols],tr.flooded); return m.predict_proba(te[cols])[:,1]
def cap(y,p,f=0.05):
    k=max(int(round(len(p)*f)),1)
    return float(y.values[np.argsort(-p)[:k]].sum())/max(float(y.sum()),1.0)

for label,dat in (("진짜 비",d),("남의 비",s)):
    ta,tb,ca,cb=[],[],[],[]
    for e in events:
        tr,te=dat[dat.event.astype(str)!=e],dat[dat.event.astype(str)==e]
        if te.flooded.sum()==0 or len(te)==0: continue
        pa=fit(tr,te,TERRAIN); pb=fit(tr,te,TERRAIN+RAIN)
        ta.append(roc_auc_score(te.flooded,pa)); tb.append(roc_auc_score(te.flooded,pb))
        ca.append(cap(te.flooded,pa)); cb.append(cap(te.flooded,pb))
    print(f"  {label:7} AUC 지형 {np.mean(ta):.3f} -> 결합 {np.mean(tb):.3f} ({np.mean(tb)-np.mean(ta):+.3f})"
          f"   상위5% {np.mean(ca)*100:5.1f}% -> {np.mean(cb)*100:5.1f}% ({(np.mean(cb)-np.mean(ca))*100:+.1f}p)  [{len(ta)}개 사건]")
