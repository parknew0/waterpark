#!/usr/bin/env python3
"""How much rain before this kind of ground goes under.

Read straight off the counted cells -- no model, no fitted curve. Ground is
split by how high it sits above the lowest point within 500 m, rain by what
fell in the six hours before the flood was surveyed, and each cell reports the
share of its cells that were recorded flooded.

The number is conditional on being inside the surveyed ring, which is where the
counting happened; it is not a national rate. Read it as "of ground like this,
that got rain like this, near where a survey went, this share went under".
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BANDS = [(-1, 2, "0~2m 거의 평지"), (2, 5, "2~5m 낮음"), (5, 15, "5~15m 보통"),
         (15, 40, "15~40m 높음"), (40, 1e9, "40m+ 매우 높음")]
# The same low ground behaves differently depending on what covers it: a paved
# block sends its rain to a drain that a field would have absorbed. This was
# the one new axis that measurably improved the model, so the table carries it.
USE = [(0.0, 0.05, "농지·녹지"), (0.05, 0.25, "저밀도 시가"), (0.25, 1.01, "고밀도 시가")]
EDGES = [0, 10, 20, 30, 40, 50, 60, 80, 100, 150, 1e9]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path,
                        default=ROOT / "data/processed/ml/training/ring_census.csv")
    parser.add_argument("--min-cells", type=int, default=300)
    parser.add_argument("--drop-dry-floods", type=float, default=0.5,
                        help="침수점 절반 이상이 6시간 1mm 미만이면 그 사건을 뺀다")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    d = pd.read_csv(args.table)
    # A storm cannot drown ground it never rained on. When most of an event's
    # flood cells show no rain in their window, the window is wrong -- a
    # missing or mistaken flood hour -- and its rows would teach that dry
    # ground floods. This drops events on a physical impossibility, not on how
    # they score.
    if args.drop_dry_floods > 0:
        share = (d[d.flooded == 1].groupby("event")
                 .rain_6h.apply(lambda s: (s < 1.0).mean()))
        bad = sorted(share[share >= args.drop_dry_floods].index.astype(str))
        if bad:
            for e in bad:
                print(f"  제외 {e}: 침수점의 {share.loc[type(share.index[0])(e)]*100:.0f}%가 "
                      f"6시간 1mm 미만 -> 누적 창이 틀렸다")
            d = d[~d.event.astype(str).isin(bad)]
            print()
    if "impervious" in d.columns:
        # 불투수면은 토지피복(환경부)과 건물 밀도 중 큰 쪽을 쓴다: 하나는
        # 2013년에 멈춰 있어 신도시를 못 보고, 다른 하나는 도로를 못 본다.
        d["sealed"] = np.maximum(d.impervious.fillna(0), d.built_ratio.fillna(0))
    base = d.flooded.mean()
    print(f"칸 {len(d):,}  침수 {int(d.flooded.sum()):,}  전체 비율 {base*100:.2f}%\n")

    labels = [f"{EDGES[i]:g}~{EDGES[i+1]:g}" if EDGES[i+1] < 1e9 else f"{EDGES[i]:g}+"
              for i in range(len(EDGES) - 1)]
    print("6시간 강수량(mm)에 따른 침수 확률")
    print(f"{'지형':18} " + " ".join(f"{l:>8}" for l in labels))
    out = {}
    for lo, hi, name in BANDS:
        b = d[(d.rel_500m >= lo) & (d.rel_500m < hi)]
        cells, series = [], {}
        for i in range(len(EDGES) - 1):
            x = b[(b.rain_6h >= EDGES[i]) & (b.rain_6h < EDGES[i + 1])]
            if len(x) >= args.min_cells:
                p = float(x.flooded.mean())
                cells.append(f"{p*100:7.2f}%")
                series[labels[i]] = {"p": round(p, 4), "n": int(len(x))}
            else:
                cells.append(f"{'-':>8}")
        print(f"{name:18} " + " ".join(cells))
        out[name] = series

    # The number a duty officer actually wants: where does it stop being rare?
    print("\n침수 확률이 기준을 처음 넘는 6시간 강수량")
    print(f"{'지형':18} {'1% 넘는 지점':>14} {'3%':>10} {'5%':>10} {'10%':>10}")
    thresholds = {}
    for lo, hi, name in BANDS:
        b = d[(d.rel_500m >= lo) & (d.rel_500m < hi)]
        row, marks = [], {}
        for level in (0.01, 0.03, 0.05, 0.10):
            hit = None
            for i in range(len(EDGES) - 1):
                x = b[(b.rain_6h >= EDGES[i]) & (b.rain_6h < EDGES[i + 1])]
                if len(x) >= args.min_cells and x.flooded.mean() >= level:
                    hit = EDGES[i]
                    break
            marks[f"{int(level*100)}%"] = hit
            row.append(f"{hit:g}mm" if hit is not None else "안 넘음")
        thresholds[name] = marks
        print(f"{name:18} " + " ".join(f"{v:>14}" if i == 0 else f"{v:>10}"
                                       for i, v in enumerate(row)))

    if "sealed" in d.columns:
        print("\n토지이용까지 나눈 침수 확률 (6시간 강수량 mm)")
        cut = [0, 30, 50, 80, 1e9]
        lab = ["0~30", "30~50", "50~80", "80+"]
        print(f"{'지형':16} {'토지이용':12} " + " ".join(f"{l:>9}" for l in lab))
        for lo, hi, name in BANDS[:4]:
            for u0, u1, uname in USE:
                b = d[(d.rel_500m >= lo) & (d.rel_500m < hi)
                      & (d.sealed >= u0) & (d.sealed < u1)]
                cells = []
                for i in range(len(cut) - 1):
                    x = b[(b.rain_6h >= cut[i]) & (b.rain_6h < cut[i + 1])]
                    cells.append(f"{x.flooded.mean()*100:8.2f}%" if len(x) >= args.min_cells
                                 else f"{'-':>9}")
                print(f"{name:16} {uname:12} " + " ".join(cells))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            {"note": "조사 범위(침수 기록 2km 이내) 안에서 센 값이며 전국 비율이 아니다",
             "cells": int(len(d)), "flooded": int(d.flooded.sum()),
             "overall_rate": round(float(base), 4),
             "probability_by_band": out, "thresholds_mm_6h": thresholds},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {args.out}")


if __name__ == "__main__":
    main()
