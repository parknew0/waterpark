#!/usr/bin/env python3
"""과적합인가 과소적합인가. 추측 말고 잰다.

세 가지를 본다.
  1. 학습 점수와 홀드아웃 점수의 간격 -- 벌어지면 과적합
  2. 모델 복잡도를 올리고 내렸을 때의 반응 -- 단순한 쪽이 나으면 과적합,
     복잡한 쪽이 나으면 과소적합
  3. 학습에 쓰는 사건 수를 늘렸을 때의 곡선 -- 아직 오르는 중이면 자료가
     부족한 것이고, 평평하면 자료가 아니라 변수나 구조의 문제다
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
BASE = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "slope_deg",
        "built_ratio", "built_count", "impervious", "water", "rain_1h", "rain_6h"]
EXTRA = ["flow_acc", "sink_depth", "curvature", "tpi_200m", "tpi_1000m",
         "drainage_density", "dist_stream", "dist_pump", "pump_capacity",
         "sewer_density"]
USE = BASE + EXTRA


def fit(tr, te, use, **kw):
    pos = max(int(tr.flooded.sum()), 1)
    p = dict(n_estimators=400, max_depth=5, learning_rate=0.05, subsample=0.8,
             colsample_bytree=0.8, min_child_weight=5, reg_lambda=2.0)
    p.update(kw)
    m = XGBClassifier(eval_metric="logloss", n_jobs=8,
                      scale_pos_weight=(len(tr) - pos) / pos, **p)
    m.fit(tr[use], tr.flooded)
    return (roc_auc_score(tr.flooded, m.predict_proba(tr[use])[:, 1]),
            roc_auc_score(te.flooded, m.predict_proba(te[use])[:, 1]),
            m.predict_proba(te[use])[:, 1])


def cap(y, p, f=0.05):
    k = max(int(round(len(p) * f)), 1)
    return y.values[np.argsort(-p)[:k]].sum() / max(y.sum(), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_poly.csv")
    ap.add_argument("--sample", type=int, default=3_000_000)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    d = pd.read_csv(a.table)
    d["event"] = d.event.astype(str)
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=USE)
    # 양성은 다 두고 음성만 줄인다: 진단을 돌릴 만큼 가볍게 하되 라벨은 보존
    pos_rows = d[d.flooded == 1]
    neg = d[d.flooded == 0]
    if len(d) > a.sample:
        neg = neg.sample(a.sample - len(pos_rows), random_state=0)
    d = pd.concat([pos_rows, neg]).sample(frac=1, random_state=0)
    ev = [e for e, n in d.groupby("event").flooded.sum().items() if n >= 20]
    print(f"칸 {len(d):,}  침수 {int(d.flooded.sum()):,}  사건 {len(ev)}\n")

    res = {}
    print("=== 1. 학습 점수 vs 홀드아웃 점수 ===")
    tr_a, te_a, te_c = [], [], []
    for e in ev:
        tr, te = d[d.event != e], d[d.event == e]
        a1, a2, p = fit(tr, te, USE)
        tr_a.append(a1); te_a.append(a2); te_c.append(cap(te.flooded, p))
    res["gap"] = {"train_auc": float(np.mean(tr_a)), "test_auc": float(np.mean(te_a)),
                  "top5": float(np.mean(te_c))}
    print(f"  학습 AUC {np.mean(tr_a):.4f}   홀드아웃 AUC {np.mean(te_a):.4f}   "
          f"간격 {np.mean(tr_a)-np.mean(te_a):+.4f}")

    print("\n=== 2. 복잡도를 바꾸면 ===")
    grid = [("아주 단순", dict(max_depth=3, n_estimators=200)),
            ("단순",      dict(max_depth=4, n_estimators=300)),
            ("현재",      dict()),
            ("복잡",      dict(max_depth=7, n_estimators=600)),
            ("아주 복잡", dict(max_depth=9, n_estimators=900))]
    res["complexity"] = {}
    for name, kw in grid:
        A, T, C = [], [], []
        for e in ev:
            tr, te = d[d.event != e], d[d.event == e]
            a1, a2, p = fit(tr, te, USE, **kw)
            A.append(a1); T.append(a2); C.append(cap(te.flooded, p))
        res["complexity"][name] = {"train": float(np.mean(A)), "test": float(np.mean(T)),
                                   "top5": float(np.mean(C))}
        print(f"  {name:10} 학습 {np.mean(A):.4f}  홀드아웃 {np.mean(T):.4f}  "
              f"간격 {np.mean(A)-np.mean(T):+.4f}  상위5% {np.mean(C)*100:5.1f}%", flush=True)

    print("\n=== 3. 학습 사건 수를 늘리면 ===")
    rng = np.random.default_rng(0)
    res["curve"] = {}
    for n in (4, 8, 14, 20, len(ev) - 1):
        C = []
        for e in ev:
            pool = [x for x in ev if x != e]
            take = list(rng.choice(pool, min(n, len(pool)), replace=False))
            tr = d[d.event.isin(take)]
            te = d[d.event == e]
            if tr.flooded.sum() < 20:
                continue
            _, _, p = fit(tr, te, USE)
            C.append(cap(te.flooded, p))
        res["curve"][n] = float(np.mean(C))
        print(f"  학습 사건 {n:3d}개 -> 상위5% {np.mean(C)*100:5.1f}%", flush=True)

    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
