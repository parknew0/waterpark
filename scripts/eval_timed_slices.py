#!/usr/bin/env python3
"""시각별로 쪼갠 자료가 실제로 나은가.

같은 폭풍의 서로 다른 시각은 강수장을 공유한다. 시각 단위로 홀드아웃하면
같은 폭풍의 18시를 배우고 21시를 맞히는 셈이 되어 점수가 부풀므로, 여기서는
날짜 단위로 통째로 뺀다. 비교 대상(사건당 한 장)도 같은 날짜 분할을 쓴다.

21 GB를 통째로 읽을 수 없으므로 음성만 줄여 표본을 만든다. 양성은 전부
남긴다 -- 0.42% 밖에 없는 쪽을 버리면 비교가 성립하지 않는다.
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


def load(path: Path, keep_neg: float, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for chunk in pd.read_csv(path, chunksize=2_000_000):
        pos = chunk[chunk.flooded == 1]
        neg = chunk[chunk.flooded == 0]
        if keep_neg < 1.0 and len(neg):
            neg = neg.iloc[rng.random(len(neg)) < keep_neg]
        out.append(pd.concat([pos, neg]))
    return pd.concat(out, ignore_index=True)


def cap(y, p, f=0.05):
    k = max(int(round(len(p) * f)), 1)
    return y.values[np.argsort(-p)[:k]].sum() / max(y.sum(), 1)


def run(d: pd.DataFrame, label: str, complexity: dict) -> dict:
    d = d.dropna(subset=USE)
    d["day"] = d.event.astype(str).str.slice(0, 8)
    days = [x for x, n in d.groupby("day").flooded.sum().items() if n >= 20]
    A, C = [], []
    for day in days:
        tr, te = d[d.day != day], d[d.day == day]
        pos = max(int(tr.flooded.sum()), 1)
        m = XGBClassifier(eval_metric="logloss", n_jobs=8, learning_rate=0.05,
                          subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                          reg_lambda=2.0, scale_pos_weight=(len(tr) - pos) / pos,
                          **complexity)
        m.fit(tr[USE], tr.flooded)
        p = m.predict_proba(te[USE])[:, 1]
        A.append(roc_auc_score(te.flooded, p)); C.append(cap(te.flooded, p))
    print(f"  {label:34} AUC {np.mean(A):.4f}  상위5% {np.mean(C)*100:5.1f}%  "
          f"[날짜 {len(days)}]", flush=True)
    return {"auc": float(np.mean(A)), "top5": float(np.mean(C)), "days": len(days)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timed", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_timed.csv")
    ap.add_argument("--single", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_poly.csv")
    ap.add_argument("--keep-neg", type=float, default=0.03)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    res = {}
    print("자료 읽는 중 (시각별 21 GB)", flush=True)
    t = load(a.timed, a.keep_neg)
    t["sewer_density"] = t.sewer_density.fillna(t.sewer_density.median())
    print(f"  시각별: {len(t):,}칸  침수 {int(t.flooded.sum()):,} "
          f"({t.flooded.mean()*100:.2f}%)", flush=True)

    s = load(a.single, a.keep_neg * 3)
    s["sewer_density"] = s.sewer_density.fillna(s.sewer_density.median())
    print(f"  기존:   {len(s):,}칸  침수 {int(s.flooded.sum()):,} "
          f"({s.flooded.mean()*100:.2f}%)\n", flush=True)

    cur = dict(n_estimators=400, max_depth=5)
    deep = dict(n_estimators=900, max_depth=9)
    res["single_cur"] = run(s, "기존 (사건당 한 장)", cur)
    res["timed_cur"] = run(t, "시각별로 쪼갬", cur)
    res["single_deep"] = run(s, "기존 + 복잡한 모델", deep)
    res["timed_deep"] = run(t, "시각별 + 복잡한 모델", deep)

    print("\n=== 기존 대비 ===")
    b = res["single_cur"]["top5"]
    for k in ("timed_cur", "single_deep", "timed_deep"):
        print(f"  {k:14} 상위5% {(res[k]['top5']-b)*100:+5.1f}p")
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
