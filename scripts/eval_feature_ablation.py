#!/usr/bin/env python3
"""Does each block of features earn its place, or was it just assumed to?

Four things were missing from the model and each has a textbook reason to
matter: upslope contributing area and the wetness index derived from it (how
much water arrives, as opposed to how high the ground sits), the peak rate
(drainage is sized for a rate, not a volume), and what fell in the day before
(a full sponge floods on less). They are added one block at a time and only
kept if the held-out storms say so.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
BASE_T = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "rel_2000m", "slope_deg", "above_river"]
HYDRO  = ["twi", "flow_acc"]
BASE_R = ["rain_1h", "rain_3h", "rain_6h", "rain_12h", "rain_24h"]
SHAPE  = ["rain_peak", "rain_peak_1h", "rain_prior", "rain_hours"]

# Adding blocks made every number worse, which points the other way: with only
# 31 storms to hold out, each extra column is another way to fit one storm's
# quirks. So the question becomes how few columns the signal actually needs.
SETS = {
    "A 2개 (rel_500m·rain_6h)":   ["rel_500m", "rain_6h"],
    "B 4개":                      ["rel_200m", "rel_500m", "rain_1h", "rain_6h"],
    "C 6개":                      ["rel_200m", "rel_500m", "above_river", "slope_deg",
                                   "rain_1h", "rain_6h"],
    "D 8개":                      ["elevation", "rel_200m", "rel_500m", "rel_1000m",
                                   "above_river", "slope_deg", "rain_1h", "rain_6h"],
    "E 기존 12개":                 BASE_T + BASE_R,
}


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(y.values[np.argsort(-p)[:k]].sum()) / max(float(y.sum()), 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, default=ROOT / "data/processed/ml/training/event_rain_terrain_v3.csv")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    cols = sorted(set(BASE_T + HYDRO + BASE_R + SHAPE))
    d = pd.read_csv(a.table).dropna(subset=cols)
    d["event"] = d.event.astype(str)
    scorable = [e for e, n in d.groupby("event").flooded.sum().items() if n > 0]
    print(f"행 {len(d):,}  양성 {int(d.flooded.sum()):,}  채점 사건 {len(scorable)}개\n")

    res = {}
    for name, use in SETS.items():
        aucs, aps, caps = [], [], []
        for ev in scorable:
            tr, te = d[d.event != ev], d[d.event == ev]
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                              reg_lambda=2.0, eval_metric="logloss", n_jobs=8,
                              scale_pos_weight=(len(tr) - pos) / pos)
            m.fit(tr[use], tr.flooded)
            p = m.predict_proba(te[use])[:, 1]
            aucs.append(roc_auc_score(te.flooded, p))
            aps.append(average_precision_score(te.flooded, p))
            caps.append(capture(te.flooded, p))
        res[name] = {"auc": float(np.mean(aucs)), "pr_auc": float(np.mean(aps)),
                     "top5": float(np.mean(caps)) * 100,
                     "per_event_auc": [round(float(x), 4) for x in aucs]}
        print(f"  {name:24} AUC {np.mean(aucs):.4f}   PR-AUC {np.mean(aps):.4f}   "
              f"상위5% {np.mean(caps)*100:5.1f}%", flush=True)

    base = res["E 기존 12개"]
    print("\n=== 기존 대비 ===")
    for name in list(SETS)[:-1]:
        r = res[name]
        wins = sum(1 for a_, b_ in zip(base["per_event_auc"], r["per_event_auc"]) if b_ > a_)
        print(f"  {name:24} AUC {r['auc']-base['auc']:+.4f}   상위5% {r['top5']-base['top5']:+.1f}p"
              f"   이긴 사건 {wins}/{len(scorable)}")
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
