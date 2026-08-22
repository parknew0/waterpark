#!/usr/bin/env python3
"""Build the Gyeongbuk-wide building centroid/elevation dataset.

Inputs are intentionally explicit so the pipeline can be rerun after the
official Korean building-register/VWorld downloads become available.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
import shapely
from shapely.geometry import shape

from data_paths import PROCESSED_BUILDINGS, ROOT

BUILDINGS = ROOT / "data/raw/overture/gyeongbuk_bbox_buildings.parquet"
DIVISIONS = ROOT / "data/raw/overture/gyeongbuk_bbox_division_area.geojson"
BOUNDARY = ROOT / "data/interim/gyeongbuk_boundary.geojson"
DEM_DIR = ROOT / "data/raw/dem"
OUT_PARQUET = PROCESSED_BUILDINGS / "gyeongbuk_buildings_elevation.parquet"
OUT_CSV_GZ = PROCESSED_BUILDINGS / "gyeongbuk_buildings_elevation.csv.gz"
OUT_SAMPLE = ROOT / "outputs/gyeongbuk-buildings/gyeongbuk_buildings_elevation_sample.csv"
OUT_MUNICIPALITY = ROOT / "outputs/gyeongbuk-buildings/gyeongbuk_buildings_by_municipality.csv"
OUT_MANIFEST = PROCESSED_BUILDINGS / "gyeongbuk_buildings_elevation.manifest.json"

OVERTURE_RELEASE = "2026-08-19.0"
COPERNICUS_RELEASE = "GLO-30 2021"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def primary_name(value: object) -> str | None:
    if isinstance(value, dict):
        result = value.get("primary")
        return str(result) if result else None
    return None


def first_source(value: object) -> tuple[str | None, str | None, str | None]:
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first.get("dataset"), first.get("license"), first.get("record_id")
    return None, None, None


def load_boundaries() -> tuple[object, list[tuple[str, object]]]:
    boundary_doc = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    province = shape(boundary_doc["features"][0]["geometry"])

    division_doc = json.loads(DIVISIONS.read_text(encoding="utf-8"))
    municipalities: list[tuple[str, object]] = []
    for feature in division_doc["features"]:
        props = feature.get("properties", {})
        name = (props.get("names") or {}).get("primary")
        if (
            props.get("country") == "KR"
            and props.get("region") == "KR-47"
            and props.get("class") == "land"
            and props.get("admin_level") == 2
            and name
        ):
            municipalities.append((str(name), shape(feature["geometry"])))
    if len(municipalities) != 22:
        raise RuntimeError(f"Expected 22 Gyeongbuk municipalities, got {len(municipalities)}")
    return province, municipalities


def dem_path(lat_tile: int, lon_tile: int) -> Path:
    stem = f"Copernicus_DSM_COG_10_N{lat_tile:02d}_00_E{lon_tile:03d}_00_DEM"
    return DEM_DIR / f"{stem}.tif"


def sample_dem(longitudes: np.ndarray, latitudes: np.ndarray) -> np.ndarray:
    values = np.full(len(longitudes), np.nan, dtype="float32")
    lat_tiles = np.floor(latitudes).astype(int)
    lon_tiles = np.floor(longitudes).astype(int)
    for lat_tile, lon_tile in sorted(set(zip(lat_tiles.tolist(), lon_tiles.tolist()))):
        mask = (lat_tiles == lat_tile) & (lon_tiles == lon_tile)
        path = dem_path(lat_tile, lon_tile)
        if not path.exists():
            continue
        indices = np.flatnonzero(mask)
        with rasterio.open(path) as src:
            raster = src.read(1, masked=True)
            rows, cols = rasterio.transform.rowcol(
                src.transform, longitudes[indices], latitudes[indices]
            )
            rows = np.asarray(rows)
            cols = np.asarray(cols)
            valid = (
                (rows >= 0)
                & (rows < src.height)
                & (cols >= 0)
                & (cols < src.width)
            )
            sampled = np.full(len(indices), np.nan, dtype="float32")
            if valid.any():
                data = raster[rows[valid], cols[valid]]
                sampled[valid] = np.ma.filled(data, np.nan).astype("float32")
            values[indices] = sampled
    return values


def local_relative_elevation(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return local minimum and relative elevation using a 3x3 0.01-degree grid.

    This is a screening feature derived from building-centroid DSM samples. It
    is not hydrologic HAND and must not be presented as a flood-depth estimate.
    """
    gx = np.floor(df["longitude"].to_numpy() * 100).astype(int)
    gy = np.floor(df["latitude"].to_numpy() * 100).astype(int)
    tmp = pd.DataFrame({"gx": gx, "gy": gy, "z": df["surface_elevation_m"].to_numpy()})
    cell_min = tmp.groupby(["gx", "gy"], dropna=False)["z"].min().to_dict()
    neighborhood_min: dict[tuple[int, int], float] = {}
    for cell in cell_min:
        x, y = cell
        candidates = [
            cell_min[(nx, ny)]
            for nx in range(x - 1, x + 2)
            for ny in range(y - 1, y + 2)
            if (nx, ny) in cell_min and not math.isnan(cell_min[(nx, ny)])
        ]
        neighborhood_min[cell] = min(candidates) if candidates else math.nan
    local_min = np.asarray([neighborhood_min[(x, y)] for x, y in zip(gx, gy)], dtype="float32")
    relative = df["surface_elevation_m"].to_numpy(dtype="float32") - local_min
    return local_min, relative


def main() -> None:
    for path in [BUILDINGS, DIVISIONS, BOUNDARY]:
        if not path.exists():
            raise FileNotFoundError(path)
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_SAMPLE.parent.mkdir(parents=True, exist_ok=True)

    province, municipalities = load_boundaries()
    columns = [
        "id", "names", "sources", "level", "height", "min_height",
        "is_underground", "num_floors", "num_floors_underground", "min_floor",
        "subtype", "class", "geometry", "has_parts", "version",
    ]
    table = pq.read_table(BUILDINGS, columns=columns)
    raw = table.to_pandas()
    geometries = shapely.from_wkb(raw.pop("geometry").to_numpy())
    points = shapely.point_on_surface(geometries)
    in_gyeongbuk = shapely.covers(province, points)
    raw = raw.loc[in_gyeongbuk].reset_index(drop=True)
    geometries = geometries[in_gyeongbuk]
    points = points[in_gyeongbuk]

    longitude = shapely.get_x(points).astype("float64")
    latitude = shapely.get_y(points).astype("float64")
    city_county = np.full(len(raw), None, dtype=object)
    for name, geometry in municipalities:
        hit = shapely.covers(geometry, points)
        city_county[hit] = name

    names = raw.pop("names").map(primary_name)
    source_parts = raw.pop("sources").map(first_source)
    source_dataset = source_parts.map(lambda x: x[0])
    source_license = source_parts.map(lambda x: x[1])
    source_record_id = source_parts.map(lambda x: x[2])

    result = pd.DataFrame({
        "building_id": raw.pop("id"),
        "province": "경상북도",
        "city_county": city_county,
        "building_name": names,
        "latitude": latitude,
        "longitude": longitude,
        "building_class": raw.pop("class"),
        "building_subtype": raw.pop("subtype"),
        "height_m_overture": raw.pop("height"),
        "min_height_m_overture": raw.pop("min_height"),
        "floor_count_overture": raw.pop("num_floors"),
        "underground_floor_count_overture": raw.pop("num_floors_underground"),
        "min_floor_overture": raw.pop("min_floor"),
        "is_underground_structure_overture": raw.pop("is_underground"),
        "has_parts_overture": raw.pop("has_parts"),
        "source_dataset": source_dataset,
        "source_license": source_license,
        "source_record_id": source_record_id,
        "overture_release": OVERTURE_RELEASE,
    })

    result["surface_elevation_m"] = sample_dem(longitude, latitude)
    local_min, relative = local_relative_elevation(result)
    result["local_approx_1km_min_surface_elevation_m"] = local_min
    result["relative_elevation_to_local_building_min_m"] = relative
    result["elevation_source"] = "Copernicus DEM GLO-30 Public"
    result["elevation_release"] = COPERNICUS_RELEASE
    result["elevation_model_type"] = "DSM_SURFACE_NOT_BARE_EARTH"
    result["relative_elevation_method"] = "3x3 grid of 0.01-degree building-centroid DSM minima"

    parking_true = (
        result["is_underground_structure_overture"].fillna(False)
        & result["building_class"].isin(["parking", "garage", "garages"])
    )
    result["underground_parking_presence"] = np.where(
        parking_true, "TRUE_OPEN_MAP_EVIDENCE", "UNKNOWN_OFFICIAL_REGISTER_BLOCKED"
    )
    result["underground_parking_evidence"] = np.where(
        parking_true,
        "Overture/OSM building class is parking/garage and is_underground=true",
        "Exact use requires Building HUB title+floor register or VWorld linked register",
    )
    result["underground_parking_is_confirmed_official"] = False
    result["geometry_wkb"] = [bytes(value) for value in shapely.to_wkb(geometries)]

    result = result.sort_values(["city_county", "building_id"], na_position="last").reset_index(drop=True)
    pq.write_table(
        pa.Table.from_pandas(result, preserve_index=False),
        OUT_PARQUET,
        compression="zstd",
        compression_level=9,
    )

    csv_columns = [column for column in result.columns if column != "geometry_wkb"]
    result[csv_columns].to_csv(OUT_CSV_GZ, index=False, encoding="utf-8-sig", compression="gzip")
    result[csv_columns].head(20_000).to_csv(OUT_SAMPLE, index=False, encoding="utf-8-sig")
    municipality = (
        result.groupby("city_county", dropna=False)
        .agg(
            building_count=("building_id", "size"),
            elevation_available_count=("surface_elevation_m", "count"),
            elevation_min_m=("surface_elevation_m", "min"),
            elevation_median_m=("surface_elevation_m", "median"),
            elevation_max_m=("surface_elevation_m", "max"),
            overture_underground_floor_value_count=("underground_floor_count_overture", "count"),
            official_underground_parking_confirmed_count=("underground_parking_is_confirmed_official", "sum"),
        )
        .reset_index()
        .sort_values("city_county")
    )
    municipality.to_csv(OUT_MUNICIPALITY, index=False, encoding="utf-8-sig")

    manifest = {
        "created_at_kst": "2026-08-22",
        "scope": "Gyeongsangbuk-do land boundary including Ulleungdo",
        "row_count": int(len(result)),
        "municipality_count": int(result["city_county"].nunique(dropna=True)),
        "municipality_null_count": int(result["city_county"].isna().sum()),
        "elevation_non_null_count": int(result["surface_elevation_m"].notna().sum()),
        "underground_parking_true_open_map_count": int(parking_true.sum()),
        "underground_parking_official_confirmed_count": 0,
        "underground_parking_unknown_count": int((~parking_true).sum()),
        "inputs": {
            str(BUILDINGS.relative_to(ROOT)): {"sha256": sha256(BUILDINGS), "release": OVERTURE_RELEASE},
            str(DIVISIONS.relative_to(ROOT)): {"sha256": sha256(DIVISIONS), "release": OVERTURE_RELEASE},
            "dem_tiles": {"count": len(list(DEM_DIR.glob("*.tif"))), "release": COPERNICUS_RELEASE},
        },
        "outputs": {
            str(OUT_PARQUET.relative_to(ROOT)): {"sha256": sha256(OUT_PARQUET)},
            str(OUT_CSV_GZ.relative_to(ROOT)): {"sha256": sha256(OUT_CSV_GZ)},
            str(OUT_SAMPLE.relative_to(ROOT)): {"sha256": sha256(OUT_SAMPLE)},
            str(OUT_MUNICIPALITY.relative_to(ROOT)): {"sha256": sha256(OUT_MUNICIPALITY)},
        },
        "critical_limitations": [
            "Overture is an open-map compilation, not the Korean official building register.",
            "Underground parking is not inferred from underground floors; unknown remains unknown.",
            "Copernicus GLO-30 is a DSM and may include buildings/vegetation.",
            "Relative elevation is a screening feature, not HAND, flow depth, or inundation probability.",
        ],
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
