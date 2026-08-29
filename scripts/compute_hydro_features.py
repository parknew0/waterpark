#!/usr/bin/env python3
"""Slope, flow accumulation and wetness index on the existing 100 m grid.

Every feature the model has is a form of "how high is this above something".
None of them says how much water arrives. Inland flooding is decided by that:
a shallow dish at the bottom of a wide catchment floods where a steeper valley
with nothing upstream does not, and the current features cannot tell them
apart.

Flow accumulation is computed with D8 on the grid the risk model already uses,
so the new columns line up with the existing bands cell for cell and can be
compared without resampling. Depressions are deliberately left unfilled: a
sink is where water actually pools, which is the thing being predicted.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]
DEM_DIR = ROOT / "data/raw/dem"
CELL_M = 100.0

NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def tile_path(lat: int, lon: int) -> Path:
    return DEM_DIR / f"Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM.tif"


def sample_dem(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Elevation for every point, read one tile at a time and vectorised."""
    out = np.full(lons.shape, np.nan, dtype="float32")
    keys = (np.floor(lats).astype(int), np.floor(lons).astype(int))
    for lat_key in np.unique(keys[0]):
        for lon_key in np.unique(keys[1]):
            path = tile_path(int(lat_key), int(lon_key))
            if not path.exists():
                continue
            mask = (keys[0] == lat_key) & (keys[1] == lon_key)
            if not mask.any():
                continue
            with rasterio.open(path) as src:
                array = src.read(1, masked=True).filled(np.nan).astype("float32")
                inv = ~src.transform
                cols, rows = inv * (lons[mask], lats[mask])
            rows = np.floor(rows).astype(int)
            cols = np.floor(cols).astype(int)
            good = (rows >= 0) & (rows < array.shape[0]) & (cols >= 0) & (cols < array.shape[1])
            values = np.full(rows.shape, np.nan, dtype="float32")
            values[good] = array[rows[good], cols[good]]
            out[mask] = values
    return out


def flow_accumulation(elevation: np.ndarray) -> np.ndarray:
    """D8 accumulation:每 cell hands its water to its steepest lower neighbour.

    Cells are settled from the highest down, so a cell's own total is final
    before it is passed on. Cells with no lower neighbour keep what they have,
    which is what a pooling hollow does.
    """
    rows, cols = elevation.shape
    finite = np.isfinite(elevation)
    filled = np.where(finite, elevation, np.inf)
    order = np.argsort(filled, axis=None)[::-1]
    acc = np.where(finite, 1.0, 0.0).astype("float32")

    flat = filled.ravel()
    acc_flat = acc.ravel()
    for index in order:
        if not np.isfinite(flat[index]):
            continue
        r, c = divmod(int(index), cols)
        here = flat[index]
        best, best_drop = -1, 0.0
        for dr, dc in NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            neighbour = nr * cols + nc
            drop = here - flat[neighbour]
            if drop <= 0 or not np.isfinite(flat[neighbour]):
                continue
            distance = math.hypot(dr, dc)
            if drop / distance > best_drop:
                best, best_drop = neighbour, drop / distance
        if best >= 0:
            acc_flat[best] += acc_flat[index]
    return acc


def slope_degrees(elevation: np.ndarray) -> np.ndarray:
    dy, dx = np.gradient(elevation, CELL_M)
    return np.degrees(np.arctan(np.hypot(dx, dy))).astype("float32")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", type=Path,
                        default=ROOT / "data/processed/serving-bundle/grid_meta.json")
    parser.add_argument("--row0", type=int, required=True)
    parser.add_argument("--col0", type=int, required=True)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--cols", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import pyproj

    # pyproj rather than serverless/projection.py: this converts millions of
    # points at once, where the runtime's pure-Python version exists to avoid
    # a Lambda dependency and converts one at a time.
    to_wgs84 = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True).transform

    meta = json.loads(args.meta.read_text(encoding="utf-8"))["grid"]
    rr = np.arange(args.row0, args.row0 + args.rows)
    cc = np.arange(args.col0, args.col0 + args.cols)
    grid_c, grid_r = np.meshgrid(cc, rr)
    xs = meta["origin_x"] + (grid_c + 0.5) * meta["cell_m"]
    ys = meta["origin_y_top"] - (grid_r + 0.5) * meta["cell_m"]

    print(f"[창] {args.rows} x {args.cols} = {args.rows*args.cols:,}칸")
    lons, lats = to_wgs84(xs, ys)
    print("[좌표] 변환 완료")

    elevation = sample_dem(lons, lats)
    print(f"[DEM] 표고 확보 {np.isfinite(elevation).sum():,}칸")

    slope = slope_degrees(np.where(np.isfinite(elevation), elevation, 0.0))
    accumulation = flow_accumulation(elevation)
    # TWI = ln(upslope area / tan slope); the floors keep a flat cell from
    # dividing by zero without pretending the slope is something it is not.
    twi = np.log((accumulation * CELL_M * CELL_M) / np.maximum(np.tan(np.radians(np.maximum(slope, 0.05))), 1e-4))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        elevation=elevation.astype("float32"),
        slope_deg=slope.astype("float32"),
        flow_acc=accumulation.astype("float32"),
        twi=twi.astype("float32"),
        window=np.array([args.row0, args.col0, args.rows, args.cols]),
    )
    print(f"[결과] {args.out}  ({args.out.stat().st_size/1e6:.1f} MB)")
    print(f"  경사 중앙 {np.nanmedian(slope):.1f}°  집수 중앙 {np.nanmedian(accumulation):.0f}칸  TWI 중앙 {np.nanmedian(twi):.1f}")


if __name__ == "__main__":
    main()
