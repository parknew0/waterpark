#!/usr/bin/env python3
"""배수밀도와 하천까지의 거리. 침수 논문이 표준으로 꼽는 인자들.

리뷰들이 도시 침수 감수성의 조건 인자를 기후·지형·토지이용·배수 네 갈래로
나누는데, 우리 모델에는 배수 갈래가 통째로 없었다. 국내 연구가 한계강우량을
정하는 유역 인자로 꼽은 다섯 가지 -- 관거밀도, 빗물받이 밀도, 유역경사,
불투수율, 펌프장 배제능력 -- 중에서도 셋이 배수 쪽이고 우리는 뒤의 둘만
가지고 있었다.

하수관 자료는 활용신청이 필요하지만 하천중심선은 이미 로컬에 있다. 물이
빠져나가는 통로가 가까이 촘촘히 있는지는 그 자체로 배수 능력이고, 논문들이
drainage density와 distance to channel을 쓰는 이유가 그것이다.

선분은 .shp의 점을 그대로 읽어 격자에 찍는다. 322만 개 선분의 형상 전체를
파싱하는 대신 각 레코드의 점들을 훑어 지나가는 칸을 표시하는 식이라,
밀도로 쓰기에 충분하면서 1 GB짜리 파일을 몇 분 안에 처리한다.
"""
from __future__ import annotations
import argparse, json, struct, time
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt, uniform_filter

ROOT = Path(__file__).resolve().parents[1]


def stream_cells(shp: Path, meta: dict) -> np.ndarray:
    """하천 선분이 지나가는 칸을 표시한 불리언 격자."""
    rows, cols, cell = meta["rows"], meta["cols"], meta["cell_m"]
    hit = np.zeros((rows, cols), dtype=bool)
    raw = np.memmap(shp, dtype=np.uint8, mode="r")
    shx = np.frombuffer(shp.with_suffix(".shx").read_bytes()[100:], dtype=">i4")
    offs = shx[0::2].astype(np.int64) * 2 + 8
    lens = shx[1::2].astype(np.int64) * 2
    n = 0
    for i in range(len(offs)):
        o, ln = offs[i], lens[i]
        if o + ln > raw.size:
            continue
        rec = raw[o:o + ln]
        if rec.size < 44:
            continue
        npts = int(np.frombuffer(rec[40:44].tobytes(), dtype="<i4")[0])
        nparts = int(np.frombuffer(rec[36:40].tobytes(), dtype="<i4")[0])
        start = 44 + nparts * 4
        need = start + npts * 16
        if npts <= 0 or need > rec.size:
            continue
        pts = np.frombuffer(rec[start:need].tobytes(), dtype="<f8").reshape(-1, 2)
        c = ((pts[:, 0] - meta["origin_x"]) // cell).astype(np.int64)
        r = ((meta["origin_y_top"] - pts[:, 1]) // cell).astype(np.int64)
        ok = (r >= 0) & (r < rows) & (c >= 0) & (c < cols)
        if ok.any():
            hit[r[ok], c[ok]] = True
        n += 1
        if n % 400_000 == 0:
            print(f"  선분 {n:,}/{len(offs):,}", flush=True)
    return hit


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--meta", type=Path,
                    default=ROOT / "data/interim/grid30/grid_meta30.json")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data/interim/grid30")
    ap.add_argument("--density-m", type=float, default=1000.0,
                    help="이 반경 안의 하천 칸 비율을 배수밀도로 쓴다")
    a = ap.parse_args()

    meta = json.loads(a.meta.read_text(encoding="utf-8"))["grid"]
    shp = ROOT / "data/raw/river-centerline/TN_RIVER_CTLN.shp"
    t = time.time()
    hit = stream_cells(shp, meta)
    print(f"[하천] 지나가는 칸 {hit.sum():,} ({hit.mean()*100:.2f}%)  {time.time()-t:.0f}초",
          flush=True)

    k = int(round(a.density_m / meta["cell_m"])) * 2 + 1
    dens = uniform_filter(hit.astype("float32"), size=k)
    np.save(a.out / "drainage_density.npy", dens)

    dist = distance_transform_edt(~hit, sampling=meta["cell_m"]).astype("float32")
    np.save(a.out / "dist_stream.npy", dist)
    print(f"[배수밀도] 중앙 {np.median(dens)*100:.2f}%  최대 {dens.max()*100:.1f}%")
    print(f"[하천거리] 중앙 {np.median(dist):.0f} m  90% {np.percentile(dist,90):.0f} m")
    print(f"  -> {a.out}")


if __name__ == "__main__":
    main()
