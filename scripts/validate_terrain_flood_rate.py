#!/usr/bin/env python3
"""Measure the flood rate by relative-elevation band, province by province.

The Gyeongbuk work rests on one observed relationship: buildings sitting
lower than their surroundings flooded far more often, from 35.5% in the
0-2 m band down to 0% above 20 m.  That single rule outperformed the
nine-feature XGBoost model, so the nationwide expansion is only worth
building if the same relationship holds outside Gyeongbuk.

The nationwide terrain table covers flooded buildings alone, which is a
numerator with no denominator.  Median relative elevation of Seoul's flooded
buildings is 15.1 m, but that says nothing until Seoul's *unflooded*
buildings are measured the same way -- a figure is only high or low relative
to its own region.

So this walks every basement building in a province, not just the flooded
ones, and reports:

    band -> buildings, flooded, flood rate

Sampling is supported because the point is the rate, not the exact count:
``--sample-every N`` keeps every Nth unflooded building while always keeping
every flooded one, then reweights the unflooded counts.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
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
from build_national_building_elevation import DEFAULT_RADIUS_M, DemReader

from data_paths import ROOT

OUT_DIR = ROOT / "data/interim/vworld-buildings"

BANDS = [(0.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 20.0), (20.0, math.inf)]


def median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    if not n:
        return math.nan
    mid = n // 2
    if n % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def quantile_table(values: list[tuple[float, bool, float]]) -> list[dict[str, Any]]:
    """Flood rate by decile of this province's own relative elevation.

    Cutting at the province's own quantiles keeps every group the same size,
    so a flat result means the feature genuinely fails to separate rather
    than that the thresholds landed badly.
    """
    if not values:
        return []
    ordered = sorted(values, key=lambda item: item[0])
    groups = 10
    size = max(1, len(ordered) // groups)
    table = []
    for index in range(groups):
        start = index * size
        end = len(ordered) if index == groups - 1 else (index + 1) * size
        chunk = ordered[start:end]
        if not chunk:
            continue
        buildings = sum(weight for _, _, weight in chunk)
        flooded = sum(1.0 for _, is_flooded, _ in chunk if is_flooded)
        table.append(
            {
                "decile": index + 1,
                "relative_elevation_range_m": [
                    round(chunk[0][0], 2),
                    round(chunk[-1][0], 2),
                ],
                "buildings": round(buildings),
                "flooded": round(flooded),
                "flood_rate": round(flooded / buildings, 6) if buildings else None,
            }
        )
    return table


def band_of(value: float) -> str:
    for low, high in BANDS:
        if low <= value < high:
            return f"{low:g}~{high:g}m" if math.isfinite(high) else f"{low:g}m 이상"
    return "unknown"


def analyse(
    province: str, shp_dir: Path, radii: list[float], sample_every: int
) -> dict[str, Any]:
    flood_union, _, _, flood_stats = load_province_floods(province)
    if flood_union is None:
        raise SystemExit(f"No flood polygons for province {province}")
    prepared = prep(flood_union)

    prj = sorted(shp_dir.glob("*.prj"))
    epsg = "5174" if prj and "5174" in prj[0].read_text(errors="ignore") else "5186"
    transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)

    reader = DemReader()
    skipped = Counter()
    seen = 0
    # One entry per radius.  Reading the DSM tile dominates the cost, so
    # several neighbourhood sizes are measured in the same pass to compare
    # which scale separates flooded from unflooded most sharply.
    values: dict[float, list[tuple[float, bool, float]]] = {r: [] for r in radii}

    for dbf_path in sorted(shp_dir.glob("*.dbf")):
        shp_path = dbf_path.with_suffix(".shp")
        kept, _ = basement_record_indexes(dbf_path)
        print(f"  [dbf] {dbf_path.name}: 지하층 건물 {len(kept):,}동", flush=True)
        if not kept:
            continue

        for index, x, y in iter_shp_centroids(shp_path, set(kept)):
            seen += 1
            lon, lat = transformer.transform(x, y)
            flooded = prepared.contains(Point(lon, lat))
            # Every positive is kept; negatives are thinned and reweighted so
            # the rate stays unbiased while the DEM work stays affordable.
            if not flooded and sample_every > 1 and seen % sample_every:
                continue
            weight = 1.0 if flooded else float(sample_every)

            surface = reader.sample(lon, lat)
            if math.isnan(surface):
                skipped["no_surface"] += 1
                continue
            for radius in radii:
                local_min = reader.window_min(lon, lat, radius)
                if math.isnan(local_min):
                    skipped[f"no_local_min_{radius:.0f}"] += 1
                    continue
                values[radius].append((surface - local_min, flooded, weight))

            if seen % 50000 == 0:
                print(f"  [scan] {seen:,}동 처리", flush=True)

    per_radius = {}
    for radius in radii:
        rows = values[radius]
        flooded_values = sorted(v for v, f, _ in rows if f)
        unflooded_values = sorted(v for v, f, _ in rows if not f)
        table = quantile_table(rows)
        rates = [r["flood_rate"] for r in table if r["flood_rate"]]
        per_radius[f"{radius:.0f}"] = {
            "quantile_bands": table,
            "median_flooded_m": round(median(flooded_values), 2) if flooded_values else None,
            "median_unflooded_m": round(median(unflooded_values), 2) if unflooded_values else None,
            # How sharply the feature separates: top decile rate over bottom.
            "rate_spread_max_over_min": round(max(rates) / min(rates), 2)
            if rates and min(rates)
            else None,
        }

    total_buildings = sum(w for r in values[radii[0]] for _, _, w in [r])
    total_flooded = sum(1 for _, f, _ in values[radii[0]] if f)
    return {
        "per_radius": per_radius,
        "province_code": province,
        "province_name": PROVINCE_NAMES.get(province, province),
        "radii_m": radii,
        "sample_every": sample_every,
        "flood_polygons": flood_stats["province_polygons"],
        "basement_buildings_scanned": seen,
        "totals": {
            "buildings": total_buildings,
            "flooded": total_flooded,
            "flood_rate": round(total_flooded / total_buildings, 6)
            if total_buildings
            else None,
        },
        "skipped": dict(skipped),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--province", required=True)
    parser.add_argument(
        "--radii-m",
        default="200,500,1000,2000",
        help="comma-separated neighbourhood radii to compare in one pass",
    )
    parser.add_argument(
        "--sample-every",
        type=int,
        default=10,
        help="keep every Nth unflooded building (flooded are always kept)",
    )
    args = parser.parse_args()

    matches = sorted(RAW_NATIONAL.glob(f"AL_D010_{args.province}_*"))
    if not matches:
        raise SystemExit(f"No snapshot for province {args.province}")
    shp_dir = matches[-1]

    radii = [float(x) for x in str(args.radii_m).split(",") if x.strip()]
    name = PROVINCE_NAMES.get(args.province, args.province)
    print(
        f"[start] {name}({args.province}) — 표본 1/{args.sample_every},"
        f" 반경 {', '.join(f'{r:.0f}m' for r in radii)}",
        flush=True,
    )

    result = analyse(args.province, shp_dir, radii, args.sample_every)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"terrain_flood_rate_{args.province}.json"
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"[결과] {name} — 반경별 분리력 비교")
    print(f"{'반경':<8}{'침수 중앙값':>12}{'비침수 중앙값':>14}{'최고/최저 침수율':>18}")
    print("-" * 54)
    for radius, info in result["per_radius"].items():
        spread = info["rate_spread_max_over_min"]
        print(
            f"{radius + 'm':<8}{info['median_flooded_m']:>12.1f}"
            f"{info['median_unflooded_m']:>14.1f}"
            f"{(f'{spread:.1f}배' if spread else '—'):>18}"
        )

    best = max(
        result["per_radius"].items(),
        key=lambda kv: kv[1]["rate_spread_max_over_min"] or 0,
    )
    print()
    print(f"[분위수] 반경 {best[0]}m 기준 (분리력 최고)")
    print(f"{'분위':<6}{'고도범위(m)':>18}{'건물':>10}{'침수':>9}{'침수율':>9}")
    print("-" * 54)
    for row in best[1]["quantile_bands"]:
        lo, hi = row["relative_elevation_range_m"]
        rate = row["flood_rate"]
        rate_text = f"{rate * 100:.2f}%" if rate is not None else "—"
        print(
            f"{row['decile']:<6}{f'{lo:.1f}~{hi:.1f}':>18}{row['buildings']:>10,}"
            f"{row['flooded']:>9,}{rate_text:>9}"
        )
    if result["skipped"]:
        print(f"  제외: {result['skipped']}")
    print(f"  저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
