#!/usr/bin/env python3
"""Built-up fraction per 100 m cell, from the building footprints already on disk.

Every feature the model has describes the shape of the ground. None of it says
what the ground is made of, and that is the difference between a field that
soaks up 60 mm and a car park that sends all of it to the nearest drain. Urban
flood models call this imperviousness; the closest thing available here without
new data is how much of each cell is under a building.

Only the .shp is read. The attributes sit in a 27 GB pile of .dbf files and
none of them are needed -- the geometry alone gives position and size. Each
polygon record carries its own bounding box, so the footprint can be taken from
that instead of walking every vertex: buildings are near-rectangular, and the
error is far smaller than the 100 m cell being filled.
"""
from __future__ import annotations
import argparse, glob, json, struct
from pathlib import Path

import numpy as np
import pyproj

ROOT = Path(__file__).resolve().parents[1]
TO_5179 = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:5179", always_xy=True).transform


def read_shp(shp: Path):
    """Bounding-box centres and areas for every polygon, via the .shx index."""
    shx = shp.with_suffix(".shx")
    idx = np.frombuffer(shx.read_bytes()[100:], dtype=">i4").reshape(-1, 2)
    offsets = idx[:, 0].astype(np.int64) * 2 + 8      # record header is 8 bytes
    raw = np.frombuffer(shp.read_bytes(), dtype=np.uint8)
    # bbox is 4 little-endian doubles starting 4 bytes into the record content
    take = (offsets[:, None] + 4 + np.arange(32)).ravel()
    ok = take.max() < len(raw)
    if not ok:
        keep = (offsets + 36) < len(raw)
        offsets = offsets[keep]
        take = (offsets[:, None] + 4 + np.arange(32)).ravel()
    box = raw[take].view("<f8").reshape(-1, 4)
    cx = (box[:, 0] + box[:, 2]) / 2.0
    cy = (box[:, 1] + box[:, 3]) / 2.0
    area = np.abs(box[:, 2] - box[:, 0]) * np.abs(box[:, 3] - box[:, 1])
    return cx, cy, area


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--buildings", default="data/raw/vworld-buildings/national/*/*.shp")
    ap.add_argument("--out", type=Path, default=ROOT / "data/interim/hydro/grid_built.npz")
    a = ap.parse_args()

    meta = json.loads((ROOT / "data/processed/serving-bundle/grid_meta.json")
                      .read_text(encoding="utf-8"))["grid"]
    rows, cols, cell = meta["rows"], meta["cols"], meta["cell_m"]
    count = np.zeros((rows, cols), dtype="int32")
    built = np.zeros((rows, cols), dtype="float32")

    total = 0
    for shp in sorted(glob.glob(a.buildings)):
        cx, cy, area = read_shp(Path(shp))
        x, y = TO_5179(cx, cy)
        r = ((meta["origin_y_top"] - y) // cell).astype(np.int64)
        c = ((x - meta["origin_x"]) // cell).astype(np.int64)
        keep = (r >= 0) & (r < rows) & (c >= 0) & (c < cols) & np.isfinite(area)
        # A footprint larger than the cell is a parse error, not a building.
        keep &= area < cell * cell * 4
        np.add.at(count, (r[keep], c[keep]), 1)
        np.add.at(built, (r[keep], c[keep]), area[keep].astype("float32"))
        total += int(keep.sum())
        print(f"  {Path(shp).parent.name}: 건물 {keep.sum():,}", flush=True)

    ratio = np.clip(built / (cell * cell), 0.0, 1.0)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, built_ratio=ratio.astype("float32"),
                        built_count=count.astype("int32"))
    filled = ratio > 0
    print(f"\n[결과] 건물 {total:,}개  건물이 있는 칸 {filled.sum():,} "
          f"({filled.mean()*100:.1f}%)  그 칸들의 건폐율 중앙 {np.median(ratio[filled])*100:.1f}%")
    print(f"  -> {a.out}")


if __name__ == "__main__":
    main()
