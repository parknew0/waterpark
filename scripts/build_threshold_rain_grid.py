#!/usr/bin/env python3
"""침수유발 기준강우량을 30 m 격자에 올린다.

강원대가 전국 1 km 격자 104,181 칸에 대해 "3시간 누적강우량이 얼마면 몇 cm
잠기는가"를 1차식으로 낸 자료다 (침수심 = 기울기 x 3시간강우 + 절편).
우리와 완전히 다른 방법으로 만든 값이라 두 가지로 쓸 수 있다 -- 우리 모델의
채점 상대이자, 그 자체로 한 개의 열이다.

자리는 국가지점번호(gid)로 적혀 있다. 한글 두 글자가 100 km 구획이고 뒤 네
자리가 그 안의 km 좌표인데, 구획이 어디서 시작하는지는 자료에 없다. 원점
후보를 넣어보고 제주와 서울이 제자리에 떨어지는 것을 골랐다:
UTM-K (700,000, 1,300,000). 다른 후보는 경도가 1도씩 밀리거나 한반도를 벗어난다.

1 km 격자도 30 m 격자도 같은 EPSG:5179 이므로 자리 맞추기는 정수 나눗셈이다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
LETTERS = "가나다라마바사아자차카타파하"
ORIGIN_X, ORIGIN_Y = 700_000, 1_300_000
KM = 1000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path,
                    default=ROOT / "data/raw/env-bigdata/flood_threshold_rain_2023.csv")
    ap.add_argument("--cols", nargs="+", default=["depth_10", "depth_20", "depth_50"])
    ap.add_argument("--rows-per-block", type=int, default=2000)
    a = ap.parse_args()

    d = pd.read_csv(a.csv, encoding="utf-8-sig")
    idx = {c: i for i, c in enumerate(LETTERS)}
    kx = d.gid.str[0].map(idx).to_numpy() * 100 + d.gid.str[2:4].astype(int).to_numpy()
    ky = d.gid.str[1].map(idx).to_numpy() * 100 + d.gid.str[4:6].astype(int).to_numpy()
    print(f"1 km 격자 {len(d):,}칸  x {kx.min()}~{kx.max()}  y {ky.min()}~{ky.max()}")

    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = g["rows"], g["cols"], g["cell_m"]
    ox, oyt = g["origin_x"], g["origin_y_top"]

    W = int(kx.max()) + 1
    H = int(ky.max()) + 1
    out = {}
    for c in a.cols:
        t = np.full(H * W, np.nan, dtype="float32")
        t[ky * W + kx] = d[c].to_numpy(dtype="float32")
        out[c] = t.reshape(H, W)

    el = np.load(G30 / "elevation.npy", mmap_mode="r")
    dst = {c: np.lib.format.open_memmap(G30 / f"thr_{c}.npy", mode="w+",
                                        dtype="float32", shape=(R, C)) for c in a.cols}
    cols = np.arange(C)
    x = ox + (cols + 0.5) * cell
    kcol = np.floor((x - ORIGIN_X) / KM).astype(np.int64)
    okc = (kcol >= 0) & (kcol < W)
    filled = 0
    land_tot = 0
    for r0 in range(0, R, a.rows_per_block):
        r1 = min(r0 + a.rows_per_block, R)
        rows = np.arange(r0, r1)
        y = oyt - (rows + 0.5) * cell
        krow = np.floor((y - ORIGIN_Y) / KM).astype(np.int64)
        okr = (krow >= 0) & (krow < H)
        e = np.asarray(el[r0:r1], dtype="float32")
        land = np.isfinite(e) & (e > 0)
        land_tot += int(land.sum())
        for c in a.cols:
            v = np.full((r1 - r0, C), np.nan, dtype="float32")
            sub = out[c][np.clip(krow, 0, H - 1)][:, np.clip(kcol, 0, W - 1)]
            v[np.ix_(okr, okc)] = sub[np.ix_(okr, okc)]
            v[~land] = np.nan
            dst[c][r0:r1] = v
            if c == a.cols[0]:
                filled += int(np.isfinite(v).sum())
        print(f"  행 {r1:,}/{R:,}", flush=True)
    for f in dst.values():
        f.flush()
    print(f"\n육지 {land_tot:,}칸 중 값이 붙은 칸 {filled:,} ({filled/land_tot*100:.1f}%)")
    for c in a.cols:
        print(f"  thr_{c}.npy 저장")


if __name__ == "__main__":
    main()
