#!/usr/bin/env python3
"""시각별 증강이 정말 소용없나 -- 이번엔 공정하게.

앞선 비교에는 결함이 둘 있었다. 표본을 만들 때 음성 보존율을 다르게 줘서
두 조건의 침수 비율이 12.4% 대 7.6%로 갈렸고, 시험 세트도 달랐다 -- 시각별
자료에서 한 날짜를 빼면 같은 칸이 여러 시점으로 중복 들어 있어 거기서 뽑은
"상위 5%"는 면적의 5%가 아니다.

여기서는 시험 세트를 한 종류로 고정한다: 사건당 한 장짜리 자료에서 그
날짜를 통째로 뺀 것. 바뀌는 것은 학습 자료뿐이고, 음성 비율도 맞춘다.
그래야 "학습 자료를 늘린 효과"만 남는다.
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


def load(path: Path, target_pos_rate: float, seed: int = 0) -> pd.DataFrame:
    """양성은 전부, 음성은 목표 비율에 맞춰 남긴다."""
    rng = np.random.default_rng(seed)
    pos_all, neg_all, n_pos, n_neg = [], [], 0, 0
    for chunk in pd.read_csv(path, chunksize=2_000_000):
        p = chunk[chunk.flooded == 1]
        n = chunk[chunk.flooded == 0]
        pos_all.append(p); n_pos += len(p); n_neg += len(n)
        neg_all.append(n)
    pos = pd.concat(pos_all, ignore_index=True)
    want_neg = int(n_pos * (1 - target_pos_rate) / target_pos_rate)
    neg = pd.concat(neg_all, ignore_index=True)
    if len(neg) > want_neg:
        neg = neg.iloc[rng.choice(len(neg), want_neg, replace=False)]
    d = pd.concat([pos, neg], ignore_index=True)
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    return d.dropna(subset=USE)


def cap(y, p, f=0.05):
    k = max(int(round(len(p) * f)), 1)
    return y.values[np.argsort(-p)[:k]].sum() / max(y.sum(), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timed", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_timed.csv")
    ap.add_argument("--single", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_poly.csv")
    ap.add_argument("--pos-rate", type=float, default=0.08,
                    help="두 자료에 같은 침수 비율을 강제한다")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    print("자료 읽는 중", flush=True)
    s = load(a.single, a.pos_rate)
    t = load(a.timed, a.pos_rate)
    for d in (s, t):
        d["day"] = d.event.astype(str).str.slice(0, 8)
    print(f"  기존:   {len(s):,}칸  침수 {s.flooded.mean()*100:.2f}%  "
          f"날짜 {s.day.nunique()}")
    print(f"  시각별: {len(t):,}칸  침수 {t.flooded.mean()*100:.2f}%  "
          f"날짜 {t.day.nunique()}\n", flush=True)

    days = [x for x, n in s.groupby("day").flooded.sum().items() if n >= 20]
    res = {}
    for label, train_src, kw in (
            ("학습: 기존",            s, dict(n_estimators=400, max_depth=5)),
            ("학습: 시각별 증강",      t, dict(n_estimators=400, max_depth=5)),
            ("학습: 기존 + 복잡",      s, dict(n_estimators=900, max_depth=9)),
            ("학습: 시각별 + 복잡",    t, dict(n_estimators=900, max_depth=9))):
        A, C = [], []
        for day in days:
            tr = train_src[train_src.day != day]
            te = s[s.day == day]          # 시험은 언제나 같은 자료
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(eval_metric="logloss", n_jobs=8, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8,
                              min_child_weight=5, reg_lambda=2.0,
                              scale_pos_weight=(len(tr) - pos) / pos, **kw)
            m.fit(tr[USE], tr.flooded)
            p = m.predict_proba(te[USE])[:, 1]
            A.append(roc_auc_score(te.flooded, p)); C.append(cap(te.flooded, p))
        res[label] = {"auc": float(np.mean(A)), "top5": float(np.mean(C))}
        print(f"  {label:22} AUC {np.mean(A):.4f}  상위5% {np.mean(C)*100:5.1f}%",
              flush=True)

    b = res["학습: 기존"]["top5"]
    print("\n=== 기존 학습 대비 ===")
    for k in list(res)[1:]:
        print(f"  {k:22} {(res[k]['top5']-b)*100:+5.1f}p")
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
