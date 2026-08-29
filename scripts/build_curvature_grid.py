#!/usr/bin/env python3
"""곡률과 TPI. 물이 모이는 자리를 지형에서 직접 읽는다.

우리 지형 변수는 전부 "주변 최저점보다 얼마나 높은가"였다. 그것은 넓은
저지대를 잘 잡지만, 같은 높이의 땅 안에서 물이 어디로 모이는지는 말하지
않는다. 곡률이 그것을 말한다 -- 오목한 자리는 사방에서 물을 받고, 볼록한
자리는 흘려보낸다.

TPI는 평균 대비 높이다. 최저점 대비(rel_*)와 달리 주변보다 낮은 쪽으로
음수가 되므로, 넓은 평지 안의 얕은 골을 구분한다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid", type=Path, default=ROOT / "data/interim/grid30")
    a = ap.parse_args()
    meta = json.loads((a.grid / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    cell = meta["cell_m"]
    el = np.load(a.grid / "elevation.npy")
    land = np.isfinite(el) & (el > 0)
    z = np.where(land, el, 0.0).astype("float32")

    # 라플라시안 = 평균 곡률. 음수면 오목(물이 모임), 양수면 볼록.
    lap = np.zeros_like(z)
    lap[1:-1, 1:-1] = (z[:-2, 1:-1] + z[2:, 1:-1] + z[1:-1, :-2] + z[1:-1, 2:]
                       - 4.0 * z[1:-1, 1:-1]) / (cell * cell)
    np.save(a.grid / "curvature.npy", np.where(land, lap, np.nan).astype("float32"))

    for radius in (200, 1000):
        k = int(round(radius / cell)) * 2 + 1
        tpi = z - uniform_filter(z, size=k)
        np.save(a.grid / f"tpi_{radius}m.npy",
                np.where(land, tpi, np.nan).astype("float32"))
        v = tpi[land]
        print(f"[TPI {radius}m] 중앙 {np.median(v):+.2f} m  "
              f"음수(주변보다 낮음) {(v < 0).mean()*100:.1f}%")
    c = lap[land]
    print(f"[곡률] 오목한 칸 {(c < 0).mean()*100:.1f}%  "
          f"중앙 {np.median(c):+.5f}")


if __name__ == "__main__":
    main()
