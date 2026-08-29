#!/usr/bin/env python3
"""Does knowing the rain improve where we say the water will go?

Terrain alone produces one ranking of the country and repeats it for every
storm. That is the standing model. The question this answers is whether the
rain that actually fell changes which low ground should be called first.

A fair comparison has to be made inside a single storm. Across storms, terrain
looks strong for the wrong reason: flood sites sit low and the controls are
drawn from the whole country, mountains included, so any terrain column
separates them without saying anything about this particular rain. Scoring each
held-out storm on its own removes that -- every row in the comparison saw the
same weather, so what remains is whether the model ranks the places that
drowned above the places that did not.

Held out by storm, never by row: the operational question is a storm nobody has
seen, and rows from the same storm share its rain field.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
TERRAIN = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "rel_2000m",
           "slope_deg", "above_river"]
RAIN = ["rain_1h", "rain_3h", "rain_6h", "rain_12h", "rain_24h"]
SETS = {"지형": TERRAIN, "강수": RAIN, "지형+강수": TERRAIN + RAIN}


def fit_score(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> np.ndarray:
    pos = max(int(train.flooded.sum()), 1)
    model = XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        reg_lambda=2.0, eval_metric="logloss", n_jobs=8,
        scale_pos_weight=(len(train) - pos) / pos,
    )
    model.fit(train[cols], train.flooded)
    return model.predict_proba(test[cols])[:, 1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path,
                        default=ROOT / "data/processed/ml/training/event_rain_terrain.csv")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--min-rain", type=float, default=0.0,
                        help="이 값 이상 비가 온 행만 비교한다(mm/24h)")
    parser.add_argument("--exclude-events", default="",
                        help="쉼표로 구분한 사건. 학습과 시험 양쪽에서 뺀다")
    parser.add_argument("--max-elev", type=float,
                        help="이 고도 이하만 비교한다. 산지를 빼고 저지대끼리 겨룬다")
    args = parser.parse_args()

    data = pd.read_csv(args.table).dropna(subset=TERRAIN + RAIN)
    # An event with no known flood hour has no correctly-built rain window: its
    # accumulation ends at midnight and mixes in hours the flood never saw.
    # Such rows are wrong rather than merely unhelpful, so they leave training
    # too -- the decision is about whether the feature can be built, not about
    # how the event scores.
    drop = [e for e in args.exclude_events.split(",") if e]
    if drop:
        data = data[~data.event.astype(str).isin(drop)]
        print(f"제외한 사건: {', '.join(drop)}")
    if args.max_elev is not None:
        data = data[data.elevation <= args.max_elev]
    if args.min_rain > 0:
        data = data[data.rain_24h >= args.min_rain]

    # A storm with no surveyed flood cannot be ranked: every row is negative and
    # AUC is undefined. Those storms still teach the model what rain looks like
    # when nothing drowns, so they stay in training and only leave the test.
    counts = data.groupby("event").flooded.agg(["size", "sum"])
    scorable = [e for e, r in counts.iterrows() if r["sum"] > 0]
    print(f"행 {len(data):,}  양성 {int(data.flooded.sum()):,} "
          f"({data.flooded.mean()*100:.2f}%)  채점 가능 사건 {len(scorable)}/{len(counts)}\n")

    results: dict[str, dict[str, dict[str, float]]] = {n: {} for n in SETS}
    for event in scorable:
        train = data[data.event != event]
        test = data[data.event == event]
        line = f"  {event}  양성 {int(test.flooded.sum()):5,}/{len(test):6,}"
        for name, cols in SETS.items():
            p = fit_score(train, test, cols)
            auc = roc_auc_score(test.flooded, p)
            ap = average_precision_score(test.flooded, p)
            results[name][event] = {"auc": round(float(auc), 4),
                                    "pr_auc": round(float(ap), 4),
                                    "base": round(float(test.flooded.mean()), 4)}
            line += f"   {name} {auc:.3f}"
        print(line, flush=True)

    print("\n=== 사건 평균 (사건 하나씩 빼고 학습) ===")
    summary = {}
    for name in SETS:
        aucs = [results[name][e]["auc"] for e in scorable]
        aps = [results[name][e]["pr_auc"] for e in scorable]
        summary[name] = {"auc_mean": round(float(np.mean(aucs)), 4),
                         "auc_min": round(float(np.min(aucs)), 4),
                         "pr_auc_mean": round(float(np.mean(aps)), 4)}
        print(f"  {name:10} AUC {np.mean(aucs):.4f}  (최저 {np.min(aucs):.3f})"
              f"   PR-AUC {np.mean(aps):.4f}")

    gain = summary["지형+강수"]["auc_mean"] - summary["지형"]["auc_mean"]
    print(f"\n  강수를 더해 얻은 것: AUC {gain:+.4f}")
    wins = sum(1 for e in scorable
               if results["지형+강수"][e]["auc"] > results["지형"][e]["auc"])
    print(f"  사건별로 이긴 횟수: {wins}/{len(scorable)}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            {"filter": {"min_rain": args.min_rain, "max_elev": args.max_elev},
             "rows": int(len(data)), "positives": int(data.flooded.sum()),
             "per_event": results, "summary": summary},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {args.out}")


if __name__ == "__main__":
    main()
