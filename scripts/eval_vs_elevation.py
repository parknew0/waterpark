#!/usr/bin/env python3
"""우리 라벨 위에서도 표고 하나가 우리 모델을 이기는가.

도로 침수 위험지점 채점에서 표고만 쓴 것(78.4%)이 우리 21 열(75.7%)을 이겼다.
두 가지 설명이 가능하다.

  갑. 우리 모델이 표고에서 얻을 것을 못 뽑아내고 있다.
  을. 도로 위험지점이 우리가 배운 것과 다른 종류의 자리다.

우리 라벨 위에서 같은 비교를 하면 갈린다. 여기서도 표고가 이기면 갑이고,
크게 지면 을이다. 시험지는 폭풍 단위로 나누고, 제품이 쓰는 지표(상위 5% 포착)로
잰다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(np.asarray(y)[np.argsort(-p)[:k]].sum()) / max(float(np.sum(y)), 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_88.csv")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--sample", type=float, default=0.35,
                    help="행을 이 비율로 고르게 뽑는다. 표 전체는 스왑에 걸려 열 배 느리다")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/vs_elevation.json")
    a = ap.parse_args()

    # float64 로 읽으면 2 천만 행이 4 GB 를 먹고 스왑에 걸린다. float32 로 절반.
    cols = sorted({*USE, "event", "flooded"})
    dt = {c: "float32" for c in cols if c not in ("event", "flooded")}
    dt.update({"event": str, "flooded": "int8"})
    d = pd.read_csv(a.table, usecols=cols, dtype=dt)
    if a.sample < 1.0:
        # 고르게 뽑는다. 표본 틀(어느 칸이 들어오는가)은 그대로이고 행만 줄인다.
        d = d.sample(frac=a.sample, random_state=0)
        print(f"행을 {a.sample*100:.0f}% 로 줄였다: {len(d):,}행")
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    ev = d.groupby("event").flooded.sum().sort_values(ascending=False)
    fold, load = {}, np.zeros(a.folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    d["fold"] = d.event.map(fold)
    print(f"행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개\n")

    res = {k: [] for k in ("우리 모델", "표고만", "주변대비 높이만", "우묵한 정도만")}
    t0 = time.time()
    for f in range(a.folds):
        tr, te = d[d.fold != f], d[d.fold == f]
        if te.flooded.sum() == 0:
            continue
        pos = max(int(tr.flooded.sum()), 1)
        m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                          scale_pos_weight=(len(tr) - pos) / pos, **MODEL_KW)
        m.fit(tr[USE], tr.flooded)
        preds = {"우리 모델": m.predict_proba(te[USE])[:, 1],
                 "표고만": -te.elevation.to_numpy(),
                 "주변대비 높이만": -te.rel_500m.to_numpy(),
                 "우묵한 정도만": te.sink_depth.to_numpy()}
        for k, p in preds.items():
            res[k].append({"auc": float(roc_auc_score(te.flooded, p)),
                           "top5": float(capture(te.flooded, p)) * 100})
        print(f"  묶음 {f+1}/{a.folds}  " +
              "  ".join(f"{k} {res[k][-1]['top5']:.1f}%" for k in res) +
              f"  ({(time.time()-t0)/60:.0f}분)", flush=True)

    print("\n=== 우리 라벨 위에서 (상위 5% 포착) ===")
    for k, v in res.items():
        print(f"  {k:<14} AUC {np.mean([x['auc'] for x in v]):.4f}   "
              f"상위5% {np.mean([x['top5'] for x in v]):5.1f}%")
    base = np.array([x["top5"] for x in res["우리 모델"]])
    print("\n=== 우리 모델 대비 (같은 묶음끼리 짝지어) ===")
    for k in list(res)[1:]:
        dd = np.array([x["top5"] for x in res[k]]) - base
        se = dd.std(ddof=1) / np.sqrt(len(dd))
        print(f"  {k:<14} {dd.mean():+.2f}p ± {se:.2f}   이긴 묶음 {int((dd>0).sum())}/{len(dd)}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
