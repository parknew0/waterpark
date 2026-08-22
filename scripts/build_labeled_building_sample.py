#!/usr/bin/env python3
"""Build a labelled positive/negative building sample for feature testing.

Every feature measured so far has been measured on flooded buildings only,
which is a numerator without a denominator.  Whether a feature is useful
depends entirely on how it differs between buildings that flooded and
buildings that did not, so this emits both.

Positives are every basement building whose footprint falls inside a
surveyed flood polygon.  Negatives are sampled from the rest, because the
question is a rate rather than a count and sampling keeps the DEM and river
work affordable.  Each row carries the sampling weight so counts can be
scaled back up honestly.

Negatives are restricted to buildings within ``--negative-radius-m`` of a
surveyed polygon, matching the pseudo-negative rule the Gyeongbuk training
table already uses: a building far from any surveyed area was not observed
to be dry, it was simply never looked at, and calling it a negative is the
mistake the preprocessing plan explicitly forbids.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import Point
from shapely.prepared import prep

from analyze_basement_flood_overlap import (
    PROVINCE_NAMES,
    RAW_NATIONAL,
    basement_record_indexes,
    iter_shp_centroids,
    load_province_floods,
)
from data_paths import ROOT

OUT_DIR = ROOT / "data/interim/vworld-buildings"


def display_path(path: Path) -> str:
    """Repo-relative when possible; a --out anywhere else still prints."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)

# Matches the surveyed-influence rule used by build_flood_training_table.py.
DEFAULT_NEGATIVE_RADIUS_M = 1000.0
# Degrees of latitude per metre, for the buffer around surveyed polygons.
DEGREES_PER_METRE = 1.0 / 111_320.0


def sample_province(
    province: str,
    shp_dir: Path,
    sample_every: int,
    negative_radius_m: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    flood_union, _, _, flood_stats = load_province_floods(province)
    if flood_union is None:
        raise SystemExit(f"No flood polygons for province {province}")
    prepared_flood = prep(flood_union)
    # Buffering in degrees is approximate, which is fine for deciding whether
    # a building sits inside the surveyed area's influence.
    surveyed = prep(flood_union.buffer(negative_radius_m * DEGREES_PER_METRE))

    prj = sorted(shp_dir.glob("*.prj"))
    epsg = "5174" if prj and "5174" in prj[0].read_text(errors="ignore") else "5186"
    transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)

    rows: list[dict[str, Any]] = []
    counts = {"scanned": 0, "positive": 0, "negative": 0, "outside_surveyed": 0}

    for dbf_path in sorted(shp_dir.glob("*.dbf")):
        shp_path = dbf_path.with_suffix(".shp")
        kept, _ = basement_record_indexes(dbf_path)
        print(f"  [dbf] {dbf_path.name}: 지하층 {len(kept):,}동", flush=True)
        if not kept:
            continue

        for index, x, y in iter_shp_centroids(shp_path, set(kept)):
            counts["scanned"] += 1
            lon, lat = transformer.transform(x, y)
            point = Point(lon, lat)
            flooded = prepared_flood.contains(point)

            if flooded:
                weight = 1.0
                counts["positive"] += 1
            else:
                if not surveyed.contains(point):
                    counts["outside_surveyed"] += 1
                    continue
                if sample_every > 1 and counts["scanned"] % sample_every:
                    continue
                weight = float(sample_every)
                counts["negative"] += 1

            record = dict(kept[index])
            record.update(
                {
                    "province_code": province,
                    "longitude": round(lon, 7),
                    "latitude": round(lat, 7),
                    "flooded": 1 if flooded else 0,
                    "sample_weight": weight,
                }
            )
            rows.append(record)

    counts["flood_polygons"] = flood_stats["province_polygons"]
    return rows, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provinces", required=True, help="comma-separated province codes")
    parser.add_argument("--sample-every", type=int, default=20)
    parser.add_argument("--negative-radius-m", type=float, default=DEFAULT_NEGATIVE_RADIUS_M)
    parser.add_argument("--out", type=Path, default=OUT_DIR / "labeled_building_sample.csv")
    args = parser.parse_args()

    codes = [c.strip() for c in args.provinces.split(",") if c.strip()]
    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    for province in codes:
        matches = sorted(RAW_NATIONAL.glob(f"AL_D010_{province}_*"))
        if not matches:
            print(f"[skip] {province}: 스냅샷 없음", file=sys.stderr)
            continue
        name = PROVINCE_NAMES.get(province, province)
        print(f"[start] {name}({province}) 표본 1/{args.sample_every}", flush=True)
        rows, counts = sample_province(
            province, matches[-1], args.sample_every, args.negative_radius_m
        )
        all_rows.extend(rows)
        summary[province] = counts
        print(
            f"  양성 {counts['positive']:,} / 음성 {counts['negative']:,}"
            f" (조사영향권 밖 제외 {counts['outside_surveyed']:,})",
            flush=True,
        )

    if not all_rows:
        raise SystemExit("No rows sampled")

    fieldnames = [
        "province_code",
        "gis_building_id",
        "pnu",
        "legal_dong_code",
        "building_use_code",
        "building_use_name",
        "approval_date",
        "underground_floor_count",
        "longitude",
        "latitude",
        "flooded",
        "sample_weight",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(all_rows)

    positives = sum(1 for r in all_rows if r["flooded"] == 1)
    print()
    print(f"[결과] {len(all_rows):,}행 (양성 {positives:,} / 음성 {len(all_rows) - positives:,})")
    print(f"  저장: {display_path(args.out)}")
    for province, counts in summary.items():
        print(f"  {PROVINCE_NAMES.get(province, province)}: {counts}")


if __name__ == "__main__":
    main()
