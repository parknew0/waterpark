#!/usr/bin/env python3
"""새로 모은 축들이 제 값을 하는가. 폭풍 77 개로 한 번에 잰다.

지금까지 판정이 애매했던 이유는 폭풍이 30 개뿐이라 묶음마다 점수가 17% 에서
66% 까지 흔들렸기 때문이다. 그 안에서 1~2%p 짜리 차이는 우연과 구분되지 않는다.
폭풍이 77 개면 오차가 줄어 지금까지 "모르겠다"였던 것들이 갈린다.

  토양 4    배수등급·유효토심·심토토성·표토자갈. 덮이지 않은 땅이 물을 머금는가
  기준강우 3 강원대가 1 km 격자마다 낸 "몇 mm 면 몇 cm 잠기는가". 우리와 완전히
            다른 방법으로 만든 값이다
  수위 3    가장 가까운 하천 관측소의 수위와 6 시간 상승폭, 그리고 그 거리
  습윤 2    TWI 와 SPI. 웅덩이 메우기를 고친 집수면적으로 다시 만든다

같은 묶음끼리 짝지어 빼고 오차를 같이 낸다. 차이가 오차의 두 배를 넘지 못하면
"졌다"가 아니라 "아직 모른다"이다. 이 구분을 안 해서 여섯 번 잘못 적었다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402

SOIL = ["soil_drain", "soil_depth", "soil_texture", "soil_stone"]
THR  = ["thr_depth_10", "thr_depth_20", "thr_depth_50"]
WL   = ["wl_level", "wl_rise_6h", "wl_dist_km"]
WET  = ["twi", "spi"]
CELL, MIN_SLOPE_DEG = 30.0, 0.05


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(np.asarray(y)[np.argsort(-p)[:k]].sum()) / max(float(np.sum(y)), 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=9)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/all_axes.json")
    a = ap.parse_args()

    head = pd.read_csv(a.table, nrows=2)
    have = set(head.columns)
    keep = sorted({*USE, "event", "flooded"} | (set(SOIL + THR + WL) & have))
    d = pd.read_csv(a.table, usecols=keep, dtype={"event": str})
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    area = np.maximum(d.flow_acc.to_numpy(), 1.0) * CELL
    tanb = np.tan(np.radians(np.maximum(d.slope_deg.to_numpy(), MIN_SLOPE_DEG)))
    d["twi"] = np.log(area / tanb)
    d["spi"] = np.log(area * tanb)

    sets = {"기존 21개": list(USE)}
    for name, cols in (("+토양", SOIL), ("+기준강우", THR), ("+수위", WL), ("+습윤", WET)):
        if set(cols) <= set(d.columns):
            sets[name] = list(USE) + cols
    allc = [c for g in (SOIL, THR, WL, WET) if set(g) <= set(d.columns) for c in g]
    sets["+전부"] = list(USE) + allc

    print(f"행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개")
    print(f"조건 {len(sets)}가지: {list(sets)}\n")

    ev = d.groupby("event").flooded.sum().sort_values(ascending=False)
    fold, load = {}, np.zeros(a.folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    d["fold"] = d.event.map(fold)
    print("묶음별 침수 칸:", [int(x) for x in load], "\n")

    res = {}
    for name, use in sets.items():
        aucs, aps, caps = [], [], []
        t0 = time.time()
        for f in range(a.folds):
            tr, te = d[d.fold != f], d[d.fold == f]
            if te.flooded.sum() == 0:
                continue
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                              scale_pos_weight=(len(tr) - pos) / pos, **MODEL_KW)
            m.fit(tr[use], tr.flooded)
            p = m.predict_proba(te[use])[:, 1]
            aucs.append(roc_auc_score(te.flooded, p))
            aps.append(average_precision_score(te.flooded, p))
            caps.append(capture(te.flooded, p))
            print(f"    {name} {f+1}/{a.folds}  AUC {aucs[-1]:.4f}  "
                  f"상위5% {caps[-1]*100:.1f}%  ({(time.time()-t0)/60:.0f}분)", flush=True)
        res[name] = {"auc": float(np.mean(aucs)), "pr_auc": float(np.mean(aps)),
                     "top5": float(np.mean(caps)) * 100,
                     "per_fold_auc": [round(float(x), 4) for x in aucs],
                     "per_fold_top5": [round(float(x) * 100, 2) for x in caps]}
        print(f"  {name:10} AUC {res[name]['auc']:.4f}  상위5% {res[name]['top5']:5.1f}%\n",
              flush=True)

    b = res["기존 21개"]
    print("=== 기존 대비 (같은 묶음끼리 짝지어) ===")
    for name in list(sets)[1:]:
        r = res[name]
        da = np.array(r["per_fold_auc"]) - np.array(b["per_fold_auc"])
        dt = np.array(r["per_fold_top5"]) - np.array(b["per_fold_top5"])
        sa, st_ = da.std(ddof=1)/np.sqrt(len(da)), dt.std(ddof=1)/np.sqrt(len(dt))
        v = "채택" if dt.mean() > 2*st_ else ("기각" if dt.mean() < -2*st_ else "판정불가")
        print(f"  {name:10} AUC {da.mean():+.4f} ± {sa:.4f}   "
              f"상위5% {dt.mean():+.2f}p ± {st_:.2f}   이긴 묶음 {int((dt>0).sum())}/{len(dt)}"
              f"   -> {v}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
