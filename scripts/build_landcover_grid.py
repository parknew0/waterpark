#!/usr/bin/env python3
"""Impervious fraction per 100 m cell, from the national land cover map.

The building-footprint proxy built earlier takes each polygon's bounding box as
its area, which overstates every L-shaped or irregular building and puts its
centre somewhere it is not. It also sees only buildings: a car park, a road and
a paved yard shed water exactly like a roof and are invisible to it.

The environment ministry's land cover map answers this directly. Its level-2
classes number 110-160 for built-up surface, and at 10 m each 100 m cell of the
model grid contains a hundred of them -- so the fraction is counted, not
estimated. Served over WCS, which returns the class codes themselves rather
than the styled picture WMS hands back.
"""
from __future__ import annotations
import argparse, io, json, subprocess, sys, time
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pyproj
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WCS = ("https://api.mcee.go.kr/geoserver/wcs?service=WCS&version=2.0.1"
       "&request=GetCoverage&coverageId={cov}&format=image/tiff"
       "&subset={ax}({x0},{x1})&subset={ay}({y0},{y1})")
# Axis labels are per-coverage and the server rejects the wrong case outright:
# lv2_2013y answers to "x y", the 2020 pieces to "X Y".
AXES = (("x", "y"), ("X", "Y"))
# 3857 national extent of EGIS__lv2_2013y
X0, X1 = 13_914_936.0, 14_401_956.0
Y0, Y1 = 3_911_907.0, 4_597_097.0
SRC_M = 10.0          # native resolution
OUT_M = 100.0         # model grid resolution
BUILT = (110, 120, 130, 140, 150, 160)     # 시가화건조지역
WATER = (710, 720)


def fetch(url: str, tries: int = 3) -> np.ndarray | None:
    for i in range(tries):
        r = subprocess.run(["/usr/bin/curl", "--silent", "--connect-timeout", "20",
                            "--max-time", "300", "--output", "-", "--config", "-"],
                           input=f'url = "{url}"\n'.encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode == 0 and r.stdout[:2] in (b"II", b"MM"):
            return np.array(Image.open(io.BytesIO(r.stdout)))
        time.sleep(3 * (i + 1))
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    # The newest national map is served as several overlapping pieces, so a
    # tile is tried against each in turn and the first one that answers wins.
    ap.add_argument("--coverage", default="EGIS__lv2_2013y",
                    help="쉼표로 여러 개를 주면 순서대로 시도한다")
    ap.add_argument("--tile-m", type=float, default=40_000.0)
    ap.add_argument("--workers", type=int, default=6,
                    help="타일을 병렬로 받는다. 응답이 느려 순차로는 네 시간이 걸린다")
    ap.add_argument("--pieces", type=Path,
                    help="조각별 bbox/축 이름 JSON. 주면 겹치는 조각만 요청한다")
    ap.add_argument("--out", type=Path, default=ROOT / "data/interim/hydro/grid_landcover.npz")
    a = ap.parse_args()

    nx = int(round((X1 - X0) / OUT_M))
    ny = int(round((Y1 - Y0) / OUT_M))
    built = np.zeros((ny, nx), dtype="float32")
    water = np.zeros((ny, nx), dtype="float32")
    seen = np.zeros((ny, nx), dtype="float32")

    pieces = json.loads(a.pieces.read_text(encoding="utf-8")) if a.pieces else None
    pieces = json.loads(a.pieces.read_text(encoding="utf-8")) if a.pieces else None
    step = int(a.tile_m)
    tiles = [(x, y) for y in range(int(Y0), int(Y1), step)
             for x in range(int(X0), int(X1), step)]

    def one(t):
        x, y = t
        x1, y1 = min(x + step, int(X1)), min(y + step, int(Y1))
        cand = a.coverage.split(",")
        if pieces:
            cand = [c for c in cand if c in pieces
                    and not (pieces[c]["bbox"][2] < x or pieces[c]["bbox"][0] > x1
                             or pieces[c]["bbox"][3] < y or pieces[c]["bbox"][1] > y1)]
        for cov in cand:
            axes = [tuple(pieces[cov]["axes"])] if pieces and cov in pieces else AXES
            for ax, ay in axes:
                arr = fetch(WCS.format(cov=cov, ax=ax, ay=ay,
                                       x0=x, x1=x1, y0=y, y1=y1), tries=1)
                if arr is not None and np.any(arr > 0):
                    return t, arr
        return t, None

    done = fail = 0
    with ThreadPoolExecutor(a.workers) as pool:
        for (x, y), arr in pool.map(one, tiles):
            if arr is None:
                fail += 1
            else:
                k = int(OUT_M / SRC_M)
                h = (arr.shape[0] // k) * k
                w = (arr.shape[1] // k) * k
                if h and w:
                    blk = arr[:h, :w].reshape(h // k, k, w // k, k)
                    b = np.isin(blk, BUILT).mean(axis=(1, 3))
                    wt = np.isin(blk, WATER).mean(axis=(1, 3))
                    c0 = int(round((x - X0) / OUT_M))
                    r0 = int(round((Y1 - (y + h * SRC_M)) / OUT_M))
                    r1, c1 = r0 + b.shape[0], c0 + b.shape[1]
                    if 0 <= r0 and 0 <= c0 and r1 <= ny and c1 <= nx:
                        built[r0:r1, c0:c1] = b
                        water[r0:r1, c0:c1] = wt
                        seen[r0:r1, c0:c1] = 1.0
                done += 1
            if (done + fail) % 20 == 0:
                print(f"  {done+fail}/{len(tiles)}  성공 {done}  실패 {fail}", flush=True)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, built_frac=built, water_frac=water, seen=seen,
                        extent=np.array([X0, Y0, X1, Y1]), cell_m=OUT_M, epsg=3857)
    got = seen > 0
    print(f"\n[결과] 타일 {done} 성공 / {fail} 실패   덮인 칸 {got.sum():,} ({got.mean()*100:.1f}%)")
    print(f"  불투수 비율 중앙(덮인 칸) {np.median(built[got])*100:.1f}%  -> {a.out}")


if __name__ == "__main__":
    main()
