#!/usr/bin/env python3
"""Which municipalities actually looked, so that "no record" can mean "dry".

The flood registry is compiled 시군구 by 시군구. Where a municipality ran the
survey, a place with no record is a place that stayed dry; where it never ran,
the same blank means nobody went. Mixing the two makes the terrain axis read
backwards -- flood sites sit at 8 m above their surroundings while the national
random controls sit at 57 m, so "low ground" ends up looking safe.

Points are attached to a municipality through the nearest 법정동 centroid. The
centroids carry about 640 m of error, which is far too coarse for terrain but
irrelevant here: municipalities are tens of kilometres across.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]


def sgg_lookup():
    raw = json.loads((ROOT / "data/interim/geocoding/legal_dong_centroids.json")
                     .read_text(encoding="utf-8"))
    codes, pts = [], []
    for code, (lon, lat, _n) in raw.items():
        codes.append(code[:5])
        pts.append((lon * 88_000, lat * 111_000))
    tree = cKDTree(np.array(pts))
    codes = np.array(codes)

    def assign(lon, lat):
        xy = np.c_[np.asarray(lon) * 88_000, np.asarray(lat) * 111_000]
        return codes[tree.query(xy, k=1)[1]]
    return assign


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-records", type=int, default=30,
                        help="이 건수 이상 침수 기록이 있는 시군구를 '조사됨'으로 본다")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "data/interim/flood-labels/surveyed_sgg.json")
    args = parser.parse_args()

    assign = sgg_lookup()
    lab = pd.read_csv(ROOT / "data/interim/flood-labels/flood_labels.csv")
    lab["sgg"] = assign(lab.lon.values, lab.lat.values)
    counts = lab.sgg.value_counts()
    surveyed = sorted(counts[counts >= args.min_records].index)

    print(f"침수 기록이 있는 시군구: {len(counts)}곳")
    print(f"  기록 {args.min_records}건 이상 -> 조사된 것으로 취급: {len(surveyed)}곳")
    print(f"  그 시군구가 담은 기록: {counts[counts >= args.min_records].sum():,}"
          f" / {len(lab):,} ({counts[counts >= args.min_records].sum()/len(lab)*100:.1f}%)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"min_records": args.min_records,
         "surveyed_sgg": surveyed,
         "records_per_sgg": {k: int(v) for k, v in counts.items()}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {args.out}")


if __name__ == "__main__":
    main()
