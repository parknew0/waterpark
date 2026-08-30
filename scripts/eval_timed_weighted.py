#!/usr/bin/env python3
"""중복을 가중치로 눌러도 시각별 증강이 안 되는가, 그리고 복잡도의 최적점.

시각별 자료는 같은 칸이 사건 안에서 여러 번 나온다. 지금은 그것을 13번으로
세므로 시점이 많은 사건이 학습을 지배하고, 순위도 그쪽으로 끌린다. 각 행에
1/n 가중치를 주면 칸 하나가 사건당 한 표만 갖는다. 실패 원인 세 가지 --
아이디어가 틀렸다 / 시각이 시 단위라 거칠다 / 중복이 왜곡했다 -- 중 셋째를
직접 겨냥한다.

복잡도는 세 번의 실험에서 일관되게 도움이 됐지만 깊이 9가 최적인지는
확인한 적이 없어 같이 훑는다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
USE = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "slope_deg",
       "built_ratio", "built_count", "impervious", "water", "rain_1h", "rain_6h",
       "flow_acc", "sink_depth", "curvature", "tpi_200m", "tpi_1000m",
       "drainage_density", "dist_stream", "dist_pump", "pump_capacity",
       "sewer_density"]


def load(path: Path, pos_rate: float, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    pos, neg = [], []
    for chunk in pd.read_csv(path, chunksize=2_000_000):
        pos.append(chunk[chunk.flooded == 1])
        neg.append(chunk[chunk.flooded == 0])
    p = pd.concat(pos, ignore_index=True)
    n = pd.concat(neg, ignore_index=True)
    want = int(len(p) * (1 - pos_rate) / pos_rate)
    if len(n) > want:
        n = n.iloc[rng.choice(len(n), want, replace=False)]
    d = pd.concat([p, n], ignore_index=True)
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=USE)
    d["day"] = d.event.astype(str).str.slice(0, 8)
    return d


def cap(y, p, f=0.05):
    k = max(int(round(len(p) * f)), 1)
    return y.values[np.argsort(-p)[:k]].sum() / max(y.sum(), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timed", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_timed.csv")
    ap.add_argument("--single", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_poly.csv")
    ap.add_argument("--pos-rate", type=float, default=0.08)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    print("자료 읽는 중", flush=True)
    s = load(a.single, a.pos_rate)
    t = load(a.timed, a.pos_rate)
    # 같은 (날짜, 칸)이 몇 번 나오는지 세어 그 역수를 가중치로 준다
    key = t.day + "_" + t.lon.round(5).astype(str) + "_" + t.lat.round(5).astype(str)
    cnt = key.map(key.value_counts())
    t["w"] = 1.0 / cnt
    s["w"] = 1.0
    print(f"  기존 {len(s):,}칸 / 시각별 {len(t):,}칸  "
          f"(칸당 평균 등장 {cnt.mean():.1f}회)\n", flush=True)

    days = [x for x, n in s.groupby("day").flooded.sum().items() if n >= 20]
    res = {}

    def go(label, src, weighted, **kw):
        A, C = [], []
        for day in days:
            tr = src[src.day != day]
            te = s[s.day == day]
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(eval_metric="logloss", n_jobs=8, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8,
                              min_child_weight=5, reg_lambda=2.0,
                              scale_pos_weight=(len(tr) - pos) / pos, **kw)
            m.fit(tr[USE], tr.flooded,
                  sample_weight=tr.w.values if weighted else None)
            p = m.predict_proba(te[USE])[:, 1]
            A.append(roc_auc_score(te.flooded, p)); C.append(cap(te.flooded, p))
        res[label] = {"auc": float(np.mean(A)), "top5": float(np.mean(C))}
        print(f"  {label:28} AUC {np.mean(A):.4f}  상위5% {np.mean(C)*100:5.1f}%",
              flush=True)

    deep = dict(n_estimators=900, max_depth=9)
    print("=== 1. 중복 가중치의 효과 (복잡한 모델 기준) ===")
    go("기존", s, False, **deep)
    go("시각별 (가중치 없음)", t, False, **deep)
    go("시각별 (1/n 가중치)", t, True, **deep)

    print("\n=== 2. 복잡도 최적점 (기존 자료) ===")
    for d_, n_ in ((5, 400), (7, 600), (9, 900), (11, 1200), (13, 1500)):
        go(f"깊이 {d_}, 나무 {n_}", s, False, n_estimators=n_, max_depth=d_)

    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
