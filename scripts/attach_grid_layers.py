#!/usr/bin/env python3
"""이미 만들어진 학습표에 격자 층을 덧붙인다.

링 센서스를 다시 돌리면 한 시간이 넘는데, 층 하나 늘리자고 그럴 이유가 없다.
표에는 경위도가 있으므로 5179 로 되돌려 칸을 찾고 층에서 값을 꺼내면 된다.

토양 네 층이 이렇게 들어오고, 앞으로 늘어날 층도 같은 길로 들어온다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--layers", nargs="+", required=True,
                    help="grid30 안의 .npy 이름 (확장자 없이)")
    ap.add_argument("--chunk", type=int, default=2_000_000)
    a = ap.parse_args()

    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = g["rows"], g["cols"], g["cell_m"]
    ox, oyt = g["origin_x"], g["origin_y_top"]
    lay = {}
    for n in a.layers:
        f = G30 / f"{n}.npy"
        if not f.exists():
            raise SystemExit(f"층이 없다: {f}")
        lay[n] = np.load(f, mmap_mode="r")
    to5179 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    if a.out.exists():
        a.out.unlink()
    total = 0
    hits = {n: 0 for n in a.layers}
    for ch in pd.read_csv(a.table, chunksize=a.chunk, dtype={"event": str}):
        x, y = to5179.transform(ch.lon.to_numpy(), ch.lat.to_numpy())
        rr = ((oyt - y) // cell).astype(np.int64)
        cc = ((x - ox) // cell).astype(np.int64)
        ok = (rr >= 0) & (rr < R) & (cc >= 0) & (cc < C)
        for n, arr in lay.items():
            v = np.full(len(ch), np.nan, dtype="float32")
            v[ok] = arr[rr[ok], cc[ok]]
            # 0 은 "조사 안 된 곳"이지 등급 0 이 아니고, 999 는 미분류다.
            # 등급으로 두면 모델이 "아주 나쁜 배수"로 읽는다.
            v[(v == 0) | (v >= 999)] = np.nan
            ch[n] = v
            hits[n] += int(np.isfinite(v).sum())
        ch.to_csv(a.out, mode="a", header=not a.out.exists(), index=False)
        total += len(ch)
        print(f"  {total:,}칸  " +
              "  ".join(f"{n} {hits[n]/total*100:.0f}%" for n in a.layers), flush=True)
    print(f"[결과] {total:,}칸 -> {a.out}")


if __name__ == "__main__":
    main()
