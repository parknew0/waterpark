#!/usr/bin/env python3
"""Attach terrain features to the nationwide flooded-building table.

Terrain is the strongest signal measured so far.  On Gyeongbuk, buildings
0-2m above their surroundings flooded 35.5% of the time and buildings 20m
above never did, and that single rule beat the nine-feature XGBoost model.
The nationwide overlap tables were built without it, so this fills the gap.

Two values are produced per building:

    surface_elevation_m   sampled from the Copernicus GLO-30 DSM
    relative_elevation_m  that value minus the lowest DSM cell within a
                          local radius, i.e. how high the building sits
                          above the bottom of its own neighbourhood

The neighbourhood minimum is read straight from the raster rather than from
other buildings' sampled points.  The Gyeongbuk pipeline used a 3x3 grid of
0.01-degree building-centroid minima, which depended on having a dense
building population in the same area; that population was Overture, which is
not available nationwide.  Reading the raster gives the same quantity without
that dependency and applies uniformly across the country.  ``--validate``
checks the substitution against the Gyeongbuk values that produced the
published figures.

GLO-30 is a DSM: values include buildings and tree canopy, so this is surface
height, not ground height.  That limitation is inherited, not introduced.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

from data_paths import ROOT

DEM_DIR = ROOT / "data/raw/dem"
OVERLAP_DIR = ROOT / "data/interim/vworld-buildings"
OUT_DIR = ROOT / "data/processed/buildings"
OUT_CSV = OUT_DIR / "national_flooded_building_terrain.csv"
MANIFEST = ROOT / "outputs/flooded-building-register/national_building_terrain.manifest.json"

GYEONGBUK_ELEVATION = OUT_DIR / "gyeongbuk_buildings_elevation.csv.gz"

# Calibrated against the published Gyeongbuk values rather than assumed.  The
# original screen took the minimum over a 3x3 block of 0.01-degree cells, an
# irregular window roughly 1-2 km across.  Measured on 4,000 Gyeongbuk
# buildings, a 1 km radius reproduces it most closely:
#
#     radius   Pearson r   median difference
#      550 m     0.845        -1.92 m
#     1000 m     0.900        +1.18 m
#     1500 m     0.905        +3.54 m
#     2000 m     0.884        +5.69 m
#
# Sampled surface elevation matches the published values exactly (max
# absolute difference 0.0 m), so only the neighbourhood definition differs.
DEFAULT_RADIUS_M = 1000.0
# GLO-30 posts every 1 arc-second in latitude.
DEGREES_PER_METRE_LAT = 1.0 / 111_320.0


class TerrainError(RuntimeError):
    pass


def tile_key(lat: float, lon: float) -> tuple[int, int]:
    return math.floor(lat), math.floor(lon)


def tile_path(lat_tile: int, lon_tile: int) -> Path:
    stem = f"Copernicus_DSM_COG_10_N{lat_tile:02d}_00_E{lon_tile:03d}_00_DEM"
    return DEM_DIR / f"{stem}.tif"


class DemReader:
    """Read DSM tiles on demand, keeping each open tile's array in memory.

    Buildings are processed tile by tile so at most one 1x1 degree array is
    held at a time.  A neighbourhood window can cross a tile edge; those
    cells are read from the neighbouring tile when it exists and dropped
    when it does not, which is recorded rather than silently ignored.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[int, int], Any] = {}
        self.stats: Counter[str] = Counter()

    def _load(self, key: tuple[int, int]):
        if key in self._cache:
            return self._cache[key]
        if len(self._cache) > 4:
            self._cache.clear()
        path = tile_path(*key)
        if not path.exists():
            self._cache[key] = None
            return None
        with rasterio.open(path) as src:
            array = src.read(1, masked=True).filled(np.nan).astype("float32")
            entry = {
                "array": array,
                "transform": src.transform,
                "height": src.height,
                "width": src.width,
                "nodata": src.nodata,
            }
        self._cache[key] = entry
        return entry

    def sample(self, lon: float, lat: float) -> float:
        entry = self._load(tile_key(lat, lon))
        if entry is None:
            self.stats["tile_missing"] += 1
            return math.nan
        row, col = rasterio.transform.rowcol(entry["transform"], lon, lat)
        if not (0 <= row < entry["height"] and 0 <= col < entry["width"]):
            self.stats["outside_tile"] += 1
            return math.nan
        value = float(entry["array"][row, col])
        if not math.isfinite(value):
            self.stats["nodata"] += 1
            return math.nan
        return value

    def window_min(self, lon: float, lat: float, radius_m: float) -> float:
        """Lowest finite DSM value within radius_m of the point."""
        d_lat = radius_m * DEGREES_PER_METRE_LAT
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        d_lon = d_lat / cos_lat

        best = math.inf
        touched = False
        for key in {
            tile_key(lat - d_lat, lon - d_lon),
            tile_key(lat - d_lat, lon + d_lon),
            tile_key(lat + d_lat, lon - d_lon),
            tile_key(lat + d_lat, lon + d_lon),
        }:
            entry = self._load(key)
            if entry is None:
                self.stats["window_tile_missing"] += 1
                continue
            top_row, left_col = rasterio.transform.rowcol(
                entry["transform"], lon - d_lon, lat + d_lat
            )
            bottom_row, right_col = rasterio.transform.rowcol(
                entry["transform"], lon + d_lon, lat - d_lat
            )
            row0 = max(0, min(int(top_row), int(bottom_row)))
            row1 = min(entry["height"], max(int(top_row), int(bottom_row)) + 1)
            col0 = max(0, min(int(left_col), int(right_col)))
            col1 = min(entry["width"], max(int(left_col), int(right_col)) + 1)
            if row0 >= row1 or col0 >= col1:
                continue
            block = entry["array"][row0:row1, col0:col1]
            finite = block[np.isfinite(block)]
            if finite.size:
                touched = True
                best = min(best, float(finite.min()))
        if not touched:
            self.stats["window_empty"] += 1
            return math.nan
        return best


def load_flooded_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(OVERLAP_DIR.glob("basement_flood_overlap_*_flooded.csv")):
        province = path.name.split("_")[-2]
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["province_code"] = province
                rows.append(row)
    if not rows:
        raise TerrainError(f"No flooded-building CSVs under {OVERLAP_DIR}")
    return rows


def annotate(rows: list[dict[str, Any]], radius_m: float) -> dict[str, Any]:
    reader = DemReader()
    # Grouping by tile keeps one raster resident instead of thrashing.
    rows.sort(
        key=lambda r: tile_key(float(r["latitude"]), float(r["longitude"]))
    )

    resolved = 0
    for index, row in enumerate(rows, start=1):
        lon = float(row["longitude"])
        lat = float(row["latitude"])
        surface = reader.sample(lon, lat)
        if math.isnan(surface):
            row["surface_elevation_m"] = ""
            row["local_min_elevation_m"] = ""
            row["relative_elevation_m"] = ""
            continue
        local_min = reader.window_min(lon, lat, radius_m)
        row["surface_elevation_m"] = round(surface, 2)
        if math.isnan(local_min):
            row["local_min_elevation_m"] = ""
            row["relative_elevation_m"] = ""
            continue
        row["local_min_elevation_m"] = round(local_min, 2)
        row["relative_elevation_m"] = round(surface - local_min, 2)
        resolved += 1
        if index % 5000 == 0:
            print(f"  [dem] {index:,}/{len(rows):,}", flush=True)

    return {"resolved": resolved, "sampling_stats": dict(reader.stats)}


def elevation_bands(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reproduce the published band table so the numbers stay comparable."""
    bands = [(0, 2), (2, 5), (5, 10), (10, 20), (20, math.inf)]
    out = []
    for low, high in bands:
        count = sum(
            1
            for r in rows
            if r.get("relative_elevation_m") not in ("", None)
            and low <= float(r["relative_elevation_m"]) < high
        )
        label = f"{low}~{high}m" if math.isfinite(high) else f"{low}m 이상"
        out.append({"band": label, "flooded_buildings": count})
    return out


def validate_against_gyeongbuk(radius_m: float, sample_size: int = 4000) -> dict[str, Any]:
    """Compare raster-window minima with the published building-point method."""
    import gzip

    if not GYEONGBUK_ELEVATION.exists():
        raise TerrainError(f"Missing {GYEONGBUK_ELEVATION}")

    reader = DemReader()
    pairs: list[tuple[float, float]] = []
    surface_diff: list[float] = []
    with gzip.open(GYEONGBUK_ELEVATION, "rt", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if index % 75 or len(pairs) >= sample_size:
                if len(pairs) >= sample_size:
                    break
                continue
            try:
                lon = float(row["longitude"])
                lat = float(row["latitude"])
                published_surface = float(row["surface_elevation_m"])
                published_relative = float(
                    row["relative_elevation_to_local_building_min_m"]
                )
            except (TypeError, ValueError):
                continue
            surface = reader.sample(lon, lat)
            if math.isnan(surface):
                continue
            local_min = reader.window_min(lon, lat, radius_m)
            if math.isnan(local_min):
                continue
            pairs.append((published_relative, surface - local_min))
            surface_diff.append(surface - published_surface)

    if len(pairs) < 100:
        raise TerrainError(f"Only {len(pairs)} comparable rows; cannot validate")

    published = np.asarray([p for p, _ in pairs], dtype="float64")
    computed = np.asarray([c for _, c in pairs], dtype="float64")
    diff = np.asarray(surface_diff, dtype="float64")
    return {
        "sample_rows": len(pairs),
        "surface_elevation_abs_diff_max_m": round(float(np.abs(diff).max()), 4),
        "surface_elevation_abs_diff_mean_m": round(float(np.abs(diff).mean()), 4),
        "relative_elevation_pearson_r": round(
            float(np.corrcoef(published, computed)[0, 1]), 4
        ),
        "relative_elevation_median_published_m": round(float(np.median(published)), 2),
        "relative_elevation_median_computed_m": round(float(np.median(computed)), 2),
        "relative_elevation_median_diff_m": round(
            float(np.median(computed - published)), 2
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radius-m", type=float, default=DEFAULT_RADIUS_M)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="compare the raster-window method against the published Gyeongbuk values and exit",
    )
    args = parser.parse_args()

    if not DEM_DIR.exists() or not any(DEM_DIR.glob("*.tif")):
        raise TerrainError(f"No DSM tiles under {DEM_DIR}; run download_copernicus_dem.py")

    if args.validate:
        result = validate_against_gyeongbuk(args.radius_m)
        print("[검증] 라스터 창 최솟값 대 기존 건물점 기반 값")
        for key, value in result.items():
            print(f"  {key}: {value}")
        return

    rows = load_flooded_rows()
    print(f"[start] 침수 건물 {len(rows):,}동에 지형 특징 부착 (반경 {args.radius_m:.0f}m)", flush=True)
    summary = annotate(rows, args.radius_m)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
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
        "surface_elevation_m",
        "local_min_elevation_m",
        "relative_elevation_m",
    ]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

    bands = elevation_bands(rows)
    manifest = {
        "rows": len(rows),
        "terrain_resolved": summary["resolved"],
        "terrain_missing": len(rows) - summary["resolved"],
        "radius_m": args.radius_m,
        "sampling_stats": summary["sampling_stats"],
        "elevation_bands": bands,
        "elevation_source": "Copernicus DEM GLO-30 (DSM)",
        "local_min_method": f"lowest finite DSM cell within {args.radius_m:.0f} m",
        "output_csv": str(OUT_CSV.relative_to(ROOT)),
        "notes": [
            "GLO-30은 DSM이라 건물과 수목 높이가 포함된다. 지반고가 아니다.",
            "주변 최저고도는 라스터에서 직접 읽는다. 경북 기존 표는 건물점 3x3 격자 최솟값을 썼다.",
            "이 표는 침수 건물만 담는다. 음성 표본에도 같은 특징을 붙여야 학습표가 된다.",
        ],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"[결과] 지형 특징 산출 {summary['resolved']:,} / {len(rows):,}동")
    print(f"  결측 사유: {summary['sampling_stats'] or '없음'}")
    print("  주변 대비 고도 분포 (침수 건물):")
    for band in bands:
        print(f"    {band['band']:>10}: {band['flooded_buildings']:>7,}동")
    print(f"  저장: {OUT_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except TerrainError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
