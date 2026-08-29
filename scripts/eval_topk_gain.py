#!/usr/bin/env python3
"""What the rain buys at the top of the list, where the product actually acts.

AUC is a whole-ranking number and a warning only ever covers the top of one. A
city can send crews to a few percent of its area, so the question is how many
of the places that drowned sit inside that few percent -- and whether knowing
the rain moves them into it.

Held out by storm, so every number is from a storm the model never saw.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
TERRAIN = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "rel_2000m",
           "slope_deg", "above_river"]
RAIN = ["rain_1h", "rain_3h", "rain_6h", "rain_12h", "rain_24h"]
FRACTIONS = (0.01, 0.05, 0.10, 0.20)


def fit_score(train, test, cols):
    pos = max(int(train.flooded.sum()), 1)
    model = XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        reg_lambda=2.0, eval_metric="logloss", n_jobs=8,
        scale_pos_weight=(len(train) - pos) / pos,
    )
    model.fit(train[cols], train.flooded)
    return model.predict_proba(test[cols])[:, 1], model


def capture(y, p, frac):
    """Share of the floods that land in the top `frac` of the ranking."""
    k = max(int(round(len(p) * frac)), 1)
    top = np.argsort(-p)[:k]
    return float(y.values[top].sum()) / max(float(y.sum()), 1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path,
                        default=ROOT / "data/processed/ml/training/event_rain_terrain.csv")
    parser.add_argument("--exclude-events", default="20220814,20230715")
    parser.add_argument("--min-rain-6h", type=float, default=0.0,
                        help="이 값 이상 비가 온 행만 비교한다(mm/6h)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    data = pd.read_csv(args.table).dropna(subset=TERRAIN + RAIN)
    # Rain can score well just by locating the storm, because floods are only
    # surveyed where the storm was. Comparing inside the wet area removes that
    # shortcut: every row here got rain, so what is left is whether the amount
    # tells the drowned places from the dry ones.
    if args.min_rain_6h > 0:
        data = data[data.rain_6h >= args.min_rain_6h]
        print(f"비 온 지역만: 6시간 {args.min_rain_6h}mm 이상")
    drop = [e for e in args.exclude_events.split(",") if e]
    if drop:
        data = data[~data.event.astype(str).isin(drop)]
    counts = data.groupby("event").flooded.sum()
    scorable = [e for e, n in counts.items() if n > 0]

    sets = {"지형": TERRAIN, "지형+강수": TERRAIN + RAIN}
    got = {n: {f: [] for f in FRACTIONS} for n in sets}
    gains = []
    print(f"{'사건':10} {'양성':>6}  " + "  ".join(
        f"{'상위'+str(int(f*100))+'%':>18}" for f in FRACTIONS))
    print(f"{'':10} {'':>6}  " + "  ".join(f"{'지형 → 지형+강수':>18}" for f in FRACTIONS))
    importance = {}
    for event in scorable:
        train, test = data[data.event != event], data[data.event == event]
        preds = {}
        for name, cols in sets.items():
            preds[name], model = fit_score(train, test, cols)
            if name == "지형+강수":
                imp = model.get_booster().get_score(importance_type="gain")
                for k, v in imp.items():
                    importance[k] = importance.get(k, 0.0) + v
        line = f"{event:10} {int(test.flooded.sum()):6,}  "
        cells = []
        for f in FRACTIONS:
            a = capture(test.flooded, preds["지형"], f)
            b = capture(test.flooded, preds["지형+강수"], f)
            got["지형"][f].append(a)
            got["지형+강수"][f].append(b)
            cells.append(f"{a*100:6.1f} → {b*100:5.1f}%")
        gains.append(capture(test.flooded, preds["지형+강수"], 0.05)
                     - capture(test.flooded, preds["지형"], 0.05))
        print(line + "  ".join(cells), flush=True)

    print("\n=== 사건 평균: 상위 x%가 잡아낸 실제 침수 비율 ===")
    summary = {}
    for f in FRACTIONS:
        a = float(np.mean(got["지형"][f])) * 100
        b = float(np.mean(got["지형+강수"][f])) * 100
        summary[f"top_{int(f*100)}pct"] = {"terrain": round(a, 1), "combined": round(b, 1)}
        print(f"  상위 {int(f*100):2d}%   지형 {a:5.1f}%   지형+강수 {b:5.1f}%   ({b-a:+.1f}p)")
    wins = sum(1 for g in gains if g > 0)
    print(f"\n  상위 5%에서 이긴 사건: {wins}/{len(scorable)}")

    total = sum(importance.values()) or 1.0
    print("\n=== 결합 모델이 실제로 쓰는 것 (gain 합, %) ===")
    for k, v in sorted(importance.items(), key=lambda x: -x[1])[:12]:
        print(f"  {k:16} {v/total*100:5.1f}%")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            {"excluded": drop, "events": scorable, "capture": summary,
             "importance_pct": {k: round(v / total * 100, 2)
                                for k, v in sorted(importance.items(), key=lambda x: -x[1])}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {args.out}")


if __name__ == "__main__":
    main()
