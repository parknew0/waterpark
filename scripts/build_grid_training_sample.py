#!/usr/bin/env python3
"""Draw training rows from the grid itself rather than from buildings.

The shipped model learned from 9,673 flooded buildings and 21,373 unflooded
ones. That sampling frame carries a bias the model cannot see past: it only
ever visited places that have a building, so flooded farmland, roads and
riverbank were absent from both classes. Measured against labels drawn without
that constraint, the model scores 0.771 while one of its own input columns
scores 0.896 -- a model losing to a column it was given.

Positives here are grid cells that any flood source touches. Negatives are
cells drawn from the same provinces and the same land, with no building
condition attached, excluding anything within a short buffer of a positive so
the two classes are not the same place labelled twice.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "serverless"))
from projection import wgs84_to_grid  # noqa: E402

GRID = ROOT / "data/processed/risk-grid/risk_grid.npz"
META = ROOT / "data/processed/serving-bundle/grid_meta.json"
LABELS = ROOT / "data/interim/flood-labels/flood_labels.csv"
OUT = ROOT / "data/processed/ml/training/grid_flood_sample.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negatives-per-positive", type=float, default=8.0)
    parser.add_argument("--buffer-cells", type=int, default=3,
                        help="양성 주변 몇 칸을 음성에서 제외할지. 같은 장소를 "
                             "양쪽에 넣지 않기 위한 것이다.")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    grid = np.load(GRID)
    meta = json.loads(META.read_text(encoding="utf-8"))["grid"]
    risk = grid["risk_score"]
    land = np.isfinite(risk)
    print(f"[격자] 육지 {land.sum():,}칸")

    positives: set[tuple[int, int]] = set()
    with LABELS.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            x, y = wgs84_to_grid(float(row["lon"]), float(row["lat"]))
            r = int((meta["origin_y_top"] - y) // meta["cell_m"])
            c = int((x - meta["origin_x"]) // meta["cell_m"])
            if 0 <= r < risk.shape[0] and 0 <= c < risk.shape[1] and land[r, c]:
                positives.add((r, c))
    # Surveyed polygons are the older, coarser half of the evidence and are
    # already on the grid as a distance band; a zero distance is a hit.
    poly_r, poly_c = np.where(land & (grid["dist_flood_m"] <= 0))
    positives.update(zip(poly_r.tolist(), poly_c.tolist()))
    print(f"[양성] {len(positives):,}칸  (점 라벨 + 폴리곤 내부)")

    mask = np.zeros(risk.shape, dtype=bool)
    rows_idx = np.fromiter((r for r, _ in positives), dtype=np.int32, count=len(positives))
    cols_idx = np.fromiter((c for _, c in positives), dtype=np.int32, count=len(positives))
    mask[rows_idx, cols_idx] = True

    # A cell next to a flooded one is not evidence of dry ground; it is the
    # same event seen one pixel over. Excluding the ring keeps the negative
    # class from being quietly contaminated with positives.
    from scipy.ndimage import binary_dilation
    near = binary_dilation(mask, iterations=args.buffer_cells)
    pool_r, pool_c = np.where(land & ~near)
    want = int(len(positives) * args.negatives_per_positive)
    rng = np.random.default_rng(0)
    pick = rng.choice(len(pool_r), min(want, len(pool_r)), replace=False)
    print(f"[음성] 후보 {len(pool_r):,}칸에서 {len(pick):,}칸 추출 "
          f"(양성의 {len(pick)/len(positives):.1f}배, 버퍼 {args.buffer_cells}칸)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row", "col", "flooded", "sample_weight"])
        for r, c in sorted(positives):
            writer.writerow([r, c, 1, 1.0])
        # Negatives stand in for the whole unsampled pool, so each carries the
        # weight of the cells it represents. Without it the fitted rate is the
        # sampling ratio rather than the real one.
        weight = round(len(pool_r) / len(pick), 4)
        for i in pick:
            writer.writerow([int(pool_r[i]), int(pool_c[i]), 0, weight])
    print(f"[결과] {len(positives)+len(pick):,}행 -> {args.out.relative_to(ROOT)}")
    print(f"  음성 가중치 {weight}  (실제 기저율 {len(positives)/land.sum()*100:.3f}%)")


if __name__ == "__main__":
    main()
