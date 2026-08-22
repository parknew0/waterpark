#!/usr/bin/env python3
"""Build terrain and river features for buildings, without picking a scale.

Two earlier choices in this pipeline turned out to be arbitrary rather than
optimal, and both were caught only by measuring:

* a 1 km neighbourhood radius was chosen to reproduce the older Gyeongbuk
  screen, but 500 m separates flooded from unflooded far better in Seoul
  (28.9x against 21.1x) while 1 km stays best in Gyeongbuk (100.3x);
* the published 0-2 / 2-5 / 5-10 m bands put 97% of Seoul's buildings into
  two buckets, hiding a signal that is plainly there once the province's own
  quantiles are used.

The lesson is that no single radius or threshold is right everywhere, so this
does not choose one.  Every radius becomes its own column and the model picks.
Nothing is replaced either -- absolute metres are kept alongside derived
values, because a tree ignores a useless column but cannot recover a
discarded one.

River features are anchored to drainage rather than to an arbitrary circle.
"Lowest point within 1 km" means a riverside park in Seoul and a paddy field
in Gyeongbuk; height above the nearest river means the same thing in both.
Distances are computed per river grade, because 84.5% of the national
centreline file is 세류 and proximity to a gully is not proximity to a river.

    surface_elevation_m
    relative_elevation_{200,500,1000,2000}m_m
    distance_to_{national_river,local_river,stream}_m
    elevation_above_nearest_{national_river,local_river,stream}_m

Coordinates: buildings arrive as EPSG:4326 lon/lat.  River geometry stays in
its native EPSG:5179 (UTM-K), a metric nationwide projection, and building
points are projected into it -- distances in degrees would be wrong, and
reprojecting a 1 GB geometry file to match the buildings would be worse.

The DSM is Copernicus GLO-30, which includes buildings and tree canopy.  A
sampled river elevation is therefore the surface at that location, which for
open water is close to the water surface but is not a surveyed water level.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import Point
from shapely.strtree import STRtree

import river_centerline as rc
from build_national_building_elevation import DemReader
from data_paths import ROOT

OUT_DIR = ROOT / "data/processed/buildings"
MANIFEST_DIR = ROOT / "outputs/flooded-building-register"

# Every scale is kept rather than one chosen; see the module docstring.
RADII_M = (200.0, 500.0, 1000.0, 2000.0)

GRADE_COLUMNS = {
    "RVC001": "national_river",
    "RVC002": "local_river",
    "RVC003": "stream",
}
# Beyond this there is no meaningful "nearest river" to speak of, and the
# search is capped so a building in the middle of nowhere does not drag the
# nearest-neighbour query across the country.
MAX_RIVER_DISTANCE_M = 20_000.0


class FeatureError(RuntimeError):
    pass


def display_path(path: Path) -> str:
    """Repo-relative when possible so manifests stay portable."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)


def build_river_index() -> dict[str, dict[str, Any]]:
    print("[river] 하천중심선 적재 중...", flush=True)
    started = time.time()
    by_grade = rc.load_by_grade(tuple(GRADE_COLUMNS))
    index: dict[str, dict[str, Any]] = {}
    for grade, lines in by_grade.items():
        if not lines:
            continue
        index[grade] = {"lines": lines, "tree": STRtree(lines)}
        print(
            f"  {rc.GRADE_NAMES[grade]}: {len(lines):,} 선분", flush=True
        )
    print(f"[river] 적재 완료 {time.time() - started:.0f}초", flush=True)
    return index


def river_features(
    index: dict[str, dict[str, Any]],
    x: float,
    y: float,
    reader: DemReader,
    to_wgs84: Transformer,
) -> dict[str, Any]:
    """Distance and height above the nearest line of each river grade."""
    point = Point(x, y)
    out: dict[str, Any] = {}
    for grade, column in GRADE_COLUMNS.items():
        entry = index.get(grade)
        if entry is None:
            out[f"distance_to_{column}_m"] = ""
            out[f"elevation_above_nearest_{column}_m"] = ""
            continue
        nearest_index = entry["tree"].nearest(point)
        if nearest_index is None:
            out[f"distance_to_{column}_m"] = ""
            out[f"elevation_above_nearest_{column}_m"] = ""
            continue
        line = entry["lines"][nearest_index]
        distance = point.distance(line)
        if distance > MAX_RIVER_DISTANCE_M:
            out[f"distance_to_{column}_m"] = ""
            out[f"elevation_above_nearest_{column}_m"] = ""
            continue
        out[f"distance_to_{column}_m"] = round(distance, 1)

        # Sample the DSM where the river actually is, not at the building.
        closest = line.interpolate(line.project(point))
        river_lon, river_lat = to_wgs84.transform(closest.x, closest.y)
        river_elevation = reader.sample(river_lon, river_lat)
        out[f"_river_elevation_{column}"] = river_elevation
    return out


def annotate(
    rows: list[dict[str, Any]],
    index: dict[str, dict[str, Any]],
    radii: tuple[float, ...],
) -> dict[str, Any]:
    reader = DemReader()
    to_5179 = Transformer.from_crs("EPSG:4326", f"EPSG:{rc.SOURCE_EPSG}", always_xy=True)
    to_4326 = Transformer.from_crs(f"EPSG:{rc.SOURCE_EPSG}", "EPSG:4326", always_xy=True)

    # Tile locality: sorting by DSM tile keeps one raster resident at a time.
    rows.sort(key=lambda r: (math.floor(float(r["latitude"])), math.floor(float(r["longitude"]))))

    stats = {"terrain_resolved": 0, "river_resolved": 0}
    started = time.time()
    for position, row in enumerate(rows, start=1):
        lon = float(row["longitude"])
        lat = float(row["latitude"])

        surface = reader.sample(lon, lat)
        row["surface_elevation_m"] = "" if math.isnan(surface) else round(surface, 2)
        for radius in radii:
            column = f"relative_elevation_{radius:.0f}m_m"
            if math.isnan(surface):
                row[column] = ""
                continue
            local_min = reader.window_min(lon, lat, radius)
            row[column] = "" if math.isnan(local_min) else round(surface - local_min, 2)
        if not math.isnan(surface):
            stats["terrain_resolved"] += 1

        x, y = to_5179.transform(lon, lat)
        features = river_features(index, x, y, reader, to_4326)
        any_river = False
        for column in GRADE_COLUMNS.values():
            distance = features.get(f"distance_to_{column}_m", "")
            row[f"distance_to_{column}_m"] = distance
            river_elevation = features.get(f"_river_elevation_{column}")
            if (
                distance != ""
                and river_elevation is not None
                and not math.isnan(river_elevation)
                and not math.isnan(surface)
            ):
                row[f"elevation_above_nearest_{column}_m"] = round(
                    surface - river_elevation, 2
                )
                any_river = True
            else:
                row[f"elevation_above_nearest_{column}_m"] = ""
        if any_river:
            stats["river_resolved"] += 1

        if position % 2000 == 0:
            rate = position / max(time.time() - started, 1e-6)
            remaining = (len(rows) - position) / max(rate, 1e-6) / 60
            print(
                f"  [feat] {position:,}/{len(rows):,}"
                f" | {rate:.0f}동/초 | 남은 {remaining:.0f}분",
                flush=True,
            )

    stats["dem_sampling"] = dict(reader.stats)
    return stats


def load_rows(source: Path) -> list[dict[str, Any]]:
    with source.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise FeatureError(f"No rows in {source}")
    for row in rows:
        if not row.get("longitude") or not row.get("latitude"):
            raise FeatureError("Input rows need longitude and latitude columns")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=OUT_DIR / "national_flooded_building_terrain.csv",
        help="CSV of buildings with longitude/latitude columns",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_DIR / "national_building_terrain_river_features.csv",
    )
    parser.add_argument("--limit", type=int, default=0, help="process only the first N rows")
    args = parser.parse_args()

    rows = load_rows(args.source)
    if args.limit:
        rows = rows[: args.limit]
    print(f"[start] 건물 {len(rows):,}동", flush=True)

    index = build_river_index()
    stats = annotate(rows, index, RADII_M)

    base_columns = [
        "province_code",
        "gis_building_id",
        "pnu",
        "legal_dong_code",
        "building_use_name",
        "underground_floor_count",
        "approval_year",
        "first_flood_year",
        "last_flood_year",
        "existed_at_flood",
        "longitude",
        "latitude",
    ]
    feature_columns = ["surface_elevation_m"]
    feature_columns += [f"relative_elevation_{r:.0f}m_m" for r in RADII_M]
    for column in GRADE_COLUMNS.values():
        feature_columns.append(f"distance_to_{column}_m")
        feature_columns.append(f"elevation_above_nearest_{column}_m")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=base_columns + feature_columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "rows": len(rows),
        "source": display_path(args.source),
        "output": display_path(args.out),
        "radii_m": list(RADII_M),
        "river_grades": {g: rc.GRADE_NAMES[g] for g in GRADE_COLUMNS},
        "max_river_distance_m": MAX_RIVER_DISTANCE_M,
        "stats": stats,
        "notes": [
            "반경을 하나 고르지 않고 4개를 모두 컬럼으로 둔다. 최적 반경이 지역마다 다르기 때문이다.",
            "하천 거리는 EPSG:5179 평면좌표에서 점-대-선으로 계산한다. 경위도 각도 거리가 아니다.",
            "하천 대비 고도는 DSM을 하천 위치에서 샘플링한 값이며 실측 수위가 아니다.",
            "세류(RVC005)는 전체 선분의 84.5%지만 침수 신호가 약해 제외했다.",
        ],
    }
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    (MANIFEST_DIR / "terrain_river_features.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"[결과] 지형 산출 {stats['terrain_resolved']:,} / 하천 산출 {stats['river_resolved']:,}")
    print(f"  저장: {display_path(args.out)}")


if __name__ == "__main__":
    try:
        main()
    except FeatureError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
