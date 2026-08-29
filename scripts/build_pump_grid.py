#!/usr/bin/env python3
"""펌프장까지의 거리와, 가까운 펌프장의 배제능력.

두 자료를 합친다. 행안부 표준데이터는 전국 591곳으로 위치가 넓게 덮이지만
용량이 없고, 국토지리정보원 자료는 220곳뿐이지만 처리능력(㎥/분)과
배수면적을 담고 있다. 논문이 꼽는 인자는 '배제능력'이므로 용량 쪽이
본질이고, 위치만 아는 곳은 거리로만 쓴다.

방향은 미리 정하지 않는다. 펌프장은 원래 잠기는 땅에 짓기 때문에 가까울수록
위험하게 나올 수도 있다 -- 실제로 침수점은 펌프장에서 6.8 km, 대조점은
17.7 km다. 그것이 '퍼낼 수단'인지 '상습 침수지 표식'인지는 사건을 빼고
검증할 때 갈린다.

국토지리정보원 좌표는 EPSG:5181(중부원점)이다. 5186으로 읽으면 위도가
1도 남쪽으로 밀려 바다에 떨어진다.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid", type=Path, default=ROOT / "data/interim/grid30")
    a = ap.parse_args()
    meta = json.loads((a.grid / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]

    pts, caps = [], []
    std = pd.read_csv(ROOT / "data/interim/drainage/pump_stations.csv")
    lon = pd.to_numeric(std.lot, errors="coerce")
    lat = pd.to_numeric(std.lat, errors="coerce")
    ok = lon.between(124, 132) & lat.between(33, 39)
    T = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    x, y = T.transform(lon[ok].values, lat[ok].values)
    pts.append(np.c_[x, y]); caps.append(np.full(ok.sum(), np.nan))

    ngii = pd.read_csv(ROOT / "data/interim/drainage/pump_ngii_raw.csv", encoding="cp949")
    T2 = pyproj.Transformer.from_crs("EPSG:5181", "EPSG:5179", always_xy=True)
    x2, y2 = T2.transform(ngii["좌표X"].values, ngii["좌표Y"].values)
    cap = ngii["처리능력"].astype(str).str.replace(",", "").str.extract(r"([\d.]+)")[0]
    pts.append(np.c_[x2, y2]); caps.append(pd.to_numeric(cap, errors="coerce").values)

    P = np.vstack(pts); K = np.concatenate(caps)
    print(f"펌프장 {len(P):,}곳 (용량 있는 것 {np.isfinite(K).sum():,})")

    r = ((meta["origin_y_top"] - P[:, 1]) // cell).astype(int)
    c = ((P[:, 0] - meta["origin_x"]) // cell).astype(int)
    inside = (r >= 0) & (r < R) & (c >= 0) & (c < C)
    seed = np.zeros((R, C), dtype=bool)
    seed[r[inside], c[inside]] = True
    dist = distance_transform_edt(~seed, sampling=cell).astype("float32")
    np.save(a.grid / "dist_pump.npy", dist)

    # 가까운 '용량 있는' 펌프장의 처리능력. 멀면 사실상 없는 것이므로
    # 거리로 나눠 감쇠시킨다.
    has = inside & np.isfinite(K)
    tree = cKDTree(P[has])
    gx = meta["origin_x"] + (np.arange(C) + 0.5) * cell
    gy = meta["origin_y_top"] - (np.arange(R) + 0.5) * cell
    out = np.zeros((R, C), dtype="float32")
    step = 512
    for i0 in range(0, R, step):
        i1 = min(i0 + step, R)
        yy = np.repeat(gy[i0:i1], C)
        xx = np.tile(gx, i1 - i0)
        d, j = tree.query(np.c_[xx, yy], k=1)
        out[i0:i1] = (K[has][j] / np.maximum(d / 1000.0, 0.5)).reshape(i1 - i0, C)
    np.save(a.grid / "pump_capacity.npy", out)
    print(f"펌프장 거리: 중앙 {np.median(dist)/1000:.1f} km")
    print(f"배제능력 지수: 중앙 {np.median(out):.1f}  상위 1% {np.percentile(out,99):.0f}")
    print(f"  -> {a.grid}")


if __name__ == "__main__":
    main()
