#!/usr/bin/env python3
"""Precompute the static flood-risk surface so serving is a lookup.

Nothing about the model is slow: XGBoost holds 400 trees in 1.36 MB and
answers in 0.5 ms.  What is slow is assembling its inputs -- the DSM is
768 MB on disk and the river index needs about 1.5 GB of memory and 7
seconds to build.  Doing that per request rules out a serverless function
and would make any server answer in seconds rather than milliseconds.

Terrain does not change between requests, so it is computed once here and
stored as a grid.  At runtime the service reads a cell and combines it with
live rainfall, which is the only genuinely time-varying input.

Two sizing decisions come from measurement rather than preference.

Cell size is 100 m because that is the resolution the labels support: the
median flood polygon is 106 m across its short axis and only 7.1% are
narrower than 30 m, so a 30 m grid would encode detail no label can score.

Coverage is the surveyed area plus a 1 km buffer, not the whole country.
That is 11,317 km² against 100,000 -- 11.3% -- and it matches the rule the
training table already uses for negatives: beyond that buffer a location was
never surveyed, so the honest answer is UNKNOWN and computing a number there
would invite reading it as safe.

Four bands are stored, because the service has to explain itself rather than
emit a bare score:

    risk_score        model output, for ranking and map shading
    rel_elev_500m     "이 위치는 주변보다 N m 낮습니다"
    elev_above_river  "국가하천 수면보다 N m 높습니다"
    dist_flood_m      "과거 침수 구역까지 N m" and the surveyed test
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_paths import ROOT

OUT_DIR = ROOT / "data/processed/risk-grid"
MANIFEST = ROOT / "outputs/flooded-building-register/risk_grid.manifest.json"

CELL_M = 100.0
# Default influence radius around a surveyed flood polygon. It matches the
# negative-label rule the model was trained under, so it is the widest radius
# whose scores rest on the same footing as the training data. --buffer-m
# trades that footing for coverage: Gyeongbuk's flood survey is the country's
# thinnest, and at 1 km only 19% of its public car parks fall inside any
# surveyed area at all.
BUFFER_M = 1000.0
# EPSG:5179 (UTM-K) covers the whole country in metres, so a grid indexed in
# this projection has square cells everywhere.
GRID_EPSG = 5179
# Chunks are square in grid space so each worker touches few DSM tiles.
TILE_CELLS = 500

NODATA_F32 = np.float32(np.nan)
NODATA_U16 = np.uint16(65535)

_WORKER: dict[str, Any] = {}


def worker_init(model_path: str, buffer_m: float) -> None:
    """Load the heavy indexes once per process, not once per cell."""
    import rasterio  # noqa: F401  (imported for the DemReader dependency)
    from pyproj import Transformer
    from shapely.strtree import STRtree
    from xgboost import XGBClassifier

    import river_centerline as rc
    from build_national_building_elevation import DemReader
    from flood_trace_index import load_flood_index

    by_grade = rc.load_by_grade(("RVC001", "RVC002"))
    _WORKER["rivers"] = {
        grade: {"lines": lines, "tree": STRtree(lines)}
        for grade, lines in by_grade.items()
        if lines
    }
    _WORKER["dem"] = DemReader()
    _WORKER["to4326"] = Transformer.from_crs(
        f"EPSG:{GRID_EPSG}", "EPSG:4326", always_xy=True
    )
    _WORKER["flood"] = load_flood_index()
    model = XGBClassifier()
    model.load_model(model_path)
    _WORKER["model"] = model
    # Passed rather than read from the module global: workers are spawned,
    # so a value set in main() would not reach them.
    _WORKER["buffer_m"] = buffer_m
    # None means "score every cell in the extent". The model's inputs are
    # elevation and river height, both available anywhere the DSM is, so
    # the survey radius was a policy about what to publish, not a limit on
    # what could be computed.
    _WORKER["fill_all"] = buffer_m is None


def compute_chunk(bounds: tuple[float, float, int, int]) -> dict[str, Any]:
    """Fill one square block of the grid. Returns arrays plus its offset."""
    from shapely.geometry import Point

    x0, y0, cols, rows = bounds
    dem = _WORKER["dem"]
    rivers = _WORKER["rivers"]
    to4326 = _WORKER["to4326"]
    flood_tree, flood_geoms = _WORKER["flood"]
    buffer_m = _WORKER["buffer_m"] or 0.0

    risk = np.full((rows, cols), NODATA_F32, dtype="float32")
    rel = np.full((rows, cols), NODATA_F32, dtype="float32")
    above = np.full((rows, cols), NODATA_F32, dtype="float32")
    dist = np.full((rows, cols), NODATA_U16, dtype="uint16")

    features: list[list[float]] = []
    slots: list[tuple[int, int]] = []

    for row in range(rows):
        # Grid rows run north to south so the array matches raster convention.
        y = y0 - (row + 0.5) * CELL_M
        for col in range(cols):
            x = x0 + (col + 0.5) * CELL_M
            point = Point(x, y)

            nearest = flood_tree.nearest(point)
            if nearest is None:
                continue
            flood_distance = point.distance(flood_geoms[nearest])
            if not _WORKER["fill_all"] and flood_distance > buffer_m:
                # Outside the surveyed influence: leave every band nodata so
                # the service answers UNKNOWN rather than a low number.
                continue
            dist[row, col] = np.uint16(min(int(round(flood_distance)), 65534))

            lon, lat = to4326.transform(x, y)
            surface = dem.sample(lon, lat)
            if math.isnan(surface):
                continue
            # Copernicus writes water as exactly 0, and open sea is flat, so
            # every sea cell reads as "at the lowest point around" -- the one
            # pattern the model treats as most dangerous. Left in, 6.4 M ocean
            # cells scored 0.59-0.80 and dragged every quantile band with them.
            if surface <= 0.0:
                continue

            relatives = []
            for radius in (200.0, 500.0, 1000.0, 2000.0):
                local_min = dem.window_min(lon, lat, radius)
                relatives.append(
                    float("nan") if math.isnan(local_min) else surface - local_min
                )
            if math.isnan(relatives[1]):
                continue
            rel[row, col] = np.float32(relatives[1])

            river_heights = []
            for grade in ("RVC001", "RVC002"):
                entry = rivers.get(grade)
                value = float("nan")
                if entry is not None:
                    index = entry["tree"].nearest(point)
                    if index is not None:
                        line = entry["lines"][index]
                        closest = line.interpolate(line.project(point))
                        river_lon, river_lat = to4326.transform(closest.x, closest.y)
                        river_elevation = dem.sample(river_lon, river_lat)
                        if not math.isnan(river_elevation):
                            value = surface - river_elevation
                river_heights.append(value)
            if not math.isnan(river_heights[0]):
                above[row, col] = np.float32(river_heights[0])

            features.append([surface] + relatives + river_heights)
            slots.append((row, col))

    if features:
        matrix = np.asarray(features, dtype="float64")
        scores = _WORKER["model"].predict_proba(matrix)[:, 1]
        for (row, col), score in zip(slots, scores):
            risk[row, col] = np.float32(score)

    return {
        "x0": x0,
        "y0": y0,
        "cols": cols,
        "rows": rows,
        "risk": risk,
        "rel": rel,
        "above": above,
        "dist": dist,
        "filled": len(slots),
    }


def build_extent(buffer_m: float) -> tuple[float, float, int, int]:
    """Grid bounds covering the surveyed area plus its buffer."""
    from flood_trace_index import surveyed_bounds

    minx, miny, maxx, maxy = surveyed_bounds(buffer_m)
    x0 = math.floor(minx / CELL_M) * CELL_M
    y1 = math.ceil(maxy / CELL_M) * CELL_M
    cols = int(math.ceil((maxx - x0) / CELL_M))
    rows = int(math.ceil((y1 - miny) / CELL_M))
    return x0, y1, cols, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    parser.add_argument("--limit-chunks", type=int, default=0, help="smoke test only")
    parser.add_argument(
        "--fill-all",
        action="store_true",
        help="범위 안의 모든 셀을 채운다. 거리 게이트를 끈다. "
        "범위는 --buffer-m 으로 계산하되 채우기에는 쓰지 않는다.",
    )
    parser.add_argument(
        "--buffer-m",
        type=float,
        default=BUFFER_M,
        help="침수 Polygon 주변 몇 m까지 채울지. 넓힐수록 커버리지는 늘지만 "
        "학습 시 음성 라벨 규칙(1000m)에서 멀어진다.",
    )
    args = parser.parse_args()

    if not args.model.exists():
        raise SystemExit(f"모델 파일이 없다: {args.model}")

    x0, y1, cols, rows = build_extent(args.buffer_m)
    print(f"[extent] {cols:,} × {rows:,} 셀 = {cols * rows / 1e6:.2f}백만 칸", flush=True)
    print(f"[extent] 원점 EPSG:{GRID_EPSG} ({x0:,.0f}, {y1:,.0f}), 셀 {CELL_M:.0f}m", flush=True)

    chunks = []
    for row0 in range(0, rows, TILE_CELLS):
        for col0 in range(0, cols, TILE_CELLS):
            chunks.append(
                (
                    x0 + col0 * CELL_M,
                    y1 - row0 * CELL_M,
                    min(TILE_CELLS, cols - col0),
                    min(TILE_CELLS, rows - row0),
                )
            )
    if args.limit_chunks:
        chunks = chunks[: args.limit_chunks]
    print(f"[plan] 청크 {len(chunks):,}개 × 워커 {args.workers}개", flush=True)

    risk = np.full((rows, cols), NODATA_F32, dtype="float32")
    rel = np.full((rows, cols), NODATA_F32, dtype="float32")
    above = np.full((rows, cols), NODATA_F32, dtype="float32")
    dist = np.full((rows, cols), NODATA_U16, dtype="uint16")

    started = time.time()
    done = filled = 0
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=worker_init,
        initargs=(str(args.model), None if args.fill_all else args.buffer_m),
    ) as pool:
        futures = {pool.submit(compute_chunk, chunk): chunk for chunk in chunks}
        for future in as_completed(futures):
            result = future.result()
            row0 = int(round((y1 - result["y0"]) / CELL_M))
            col0 = int(round((result["x0"] - x0) / CELL_M))
            r, c = result["rows"], result["cols"]
            risk[row0 : row0 + r, col0 : col0 + c] = result["risk"]
            rel[row0 : row0 + r, col0 : col0 + c] = result["rel"]
            above[row0 : row0 + r, col0 : col0 + c] = result["above"]
            dist[row0 : row0 + r, col0 : col0 + c] = result["dist"]
            done += 1
            filled += result["filled"]
            if done % 20 == 0 or done == len(chunks):
                elapsed = time.time() - started
                rate = done / max(elapsed, 1e-6)
                print(
                    f"  [{done:,}/{len(chunks):,}] 채운 칸 {filled:,}"
                    f" | {elapsed / 60:.1f}분 | 남은 {(len(chunks) - done) / rate / 60:.1f}분",
                    flush=True,
                )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT_DIR / "risk_grid.npz",
        risk_score=risk,
        rel_elev_500m=rel,
        elev_above_national_river=above,
        dist_flood_m=dist,
    )
    grid_bytes = (OUT_DIR / "risk_grid.npz").stat().st_size

    manifest = {
        "grid": {
            "epsg": GRID_EPSG,
            "cell_m": CELL_M,
            "origin_x": x0,
            "origin_y_top": y1,
            "cols": cols,
            "rows": rows,
        },
        "coverage": {
            "rule": ("범위 안 전체 셀" if args.fill_all
                     else f"침수 Polygon 합집합 + {args.buffer_m:.0f}m 버퍼"),
            "cells_total": cols * rows,
            "cells_filled": filled,
            "fill_ratio": round(filled / (cols * rows), 4),
        },
        "bands": {
            "risk_score": "float32, XGBoost 출력. 순위 점수이며 확률이 아니다.",
            "rel_elev_500m": "float32, 반경 500m 최저점 대비 높이(m)",
            "elev_above_national_river": "float32, 최근접 국가하천 수면 대비 높이(m)",
            "dist_flood_m": "uint16, 과거 침수 Polygon까지 거리(m). 65535는 미조사",
        },
        "output_bytes": grid_bytes,
        "elapsed_minutes": round((time.time() - started) / 60, 1),
        "notes": [
            "셀 100m는 침수 Polygon 짧은 폭 중앙값 106m에 맞춘 값이다.",
            "버퍼 밖은 전 밴드 nodata이며 서비스는 UNKNOWN을 반환해야 한다. 안전이 아니다.",
            "risk_score는 지표면 침수 순위 점수다. 지하주차장 침수 확률이 아니다.",
        ],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"[결과] 채운 칸 {filled:,} / 전체 {cols * rows:,} ({filled / (cols * rows) * 100:.1f}%)")
    print(f"  격자 파일 {grid_bytes / 1e6:.1f} MB -> {(OUT_DIR / 'risk_grid.npz').relative_to(ROOT)}")
    print(f"  소요 {(time.time() - started) / 60:.1f}분")


if __name__ == "__main__":
    main()
