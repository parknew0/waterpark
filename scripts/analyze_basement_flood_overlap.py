#!/usr/bin/env python3
"""Count basement-holding buildings that fall inside historical flood polygons.

This is the decisive feasibility test for expanding Waterpark's underground
parking model beyond Gyeongbuk.  For one province it answers a single
question:

    Of the buildings whose GIS attribute says they have at least one
    underground floor (``A27`` >= 1), how many sit inside a surveyed flood
    trace polygon for that same province?

Gyeongbuk's answer was 176 buildings out of 25,336 (0.69%).  A province is
only worth collecting Building HUB register rows for if that count is large
enough to support supervised learning.

Methodology intentionally mirrors ``build_flood_training_table.py``:

* a building is represented by the centroid of its polygon,
* a building counts as flooded when that centroid falls inside the union of
  the province's flood polygons,
* source geometry is never modified; invalid polygons are repaired with
  ``make_valid`` only for the in-memory union.

The VWorld shapefiles are large (Seoul's DBF alone is 1.2 GB), so both the
DBF and the SHP are streamed record by record rather than loaded at once.
"""

from __future__ import annotations

import argparse
import csv
import json
import mmap
import struct
import sys
from pathlib import Path
from collections import Counter
from typing import Any, Iterator

from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

from data_paths import ROOT

RAW_NATIONAL = ROOT / "data/raw/vworld-buildings/national"
FLOOD_GEOJSON = ROOT / "data/raw/flood-trace/korea_flood_2002_2022.geojson"
OUT_DIR = ROOT / "data/interim/vworld-buildings"

SHAPE_TYPE_POLYGON = 5
SHAPE_TYPE_NULL = 0

PROVINCE_NAMES = {
    "11": "서울특별시",
    "26": "부산광역시",
    "27": "대구광역시",
    "28": "인천광역시",
    "29": "광주광역시",
    "30": "대전광역시",
    "31": "울산광역시",
    "36": "세종특별자치시",
    "41": "경기도",
    "42": "강원특별자치도",
    "43": "충청북도",
    "44": "충청남도",
    "45": "전북특별자치도",
    "46": "전라남도",
    "47": "경상북도",
    "48": "경상남도",
    "50": "제주특별자치도",
}


class OverlapError(RuntimeError):
    pass


def display_path(path: Path) -> str:
    """Repo-relative path when possible, absolute otherwise."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)


def dbf_layout(path: Path) -> tuple[int, int, int, dict[str, tuple[int, int]]]:
    """Return row count, header length, record length and field offsets."""
    with path.open("rb") as stream:
        header = stream.read(32)
        row_count = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]
        fields: dict[str, tuple[int, int]] = {}
        offset = 1  # deletion marker
        while True:
            descriptor = stream.read(32)
            if not descriptor or descriptor[0] == 0x0D:
                break
            name = descriptor[:11].split(b"\0", 1)[0].decode("ascii")
            length = descriptor[16]
            fields[name] = (offset, length)
            offset += length
    return row_count, header_length, record_length, fields


def integer_or_none(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def basement_record_indexes(dbf_path: Path) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    """Stream the DBF and keep only records whose A27 (지하층수) is >= 1.

    Returns a mapping of zero-based record index -> attributes, so the SHP
    reader can pick out the matching geometry by position.
    """
    row_count, header_length, record_length, fields = dbf_layout(dbf_path)
    required = {"A1", "A2", "A3", "A8", "A9", "A27"}
    missing = sorted(required - fields.keys())
    if missing:
        raise OverlapError(f"{dbf_path.name} is missing expected fields: {missing}")

    kept: dict[int, dict[str, Any]] = {}
    stats = {
        "dbf_declared_rows": row_count,
        "deleted_rows": 0,
        "a27_missing_or_blank": 0,
        "a27_zero_or_negative": 0,
        "basement_rows": 0,
    }

    with dbf_path.open("rb") as stream:
        mm = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for index in range(row_count):
                start = header_length + index * record_length
                if mm[start : start + 1] == b"*":
                    stats["deleted_rows"] += 1
                    continue

                def raw(name: str) -> bytes:
                    offset, length = fields[name]
                    return mm[start + offset : start + offset + length]

                def ascii_value(name: str) -> str:
                    return raw(name).decode("ascii", "ignore").replace("\x00", "").strip()

                def korean_value(name: str) -> str:
                    return raw(name).decode("cp949", "ignore").replace("\x00", "").strip()

                underground = integer_or_none(ascii_value("A27"))
                if underground is None:
                    stats["a27_missing_or_blank"] += 1
                    continue
                if underground <= 0:
                    stats["a27_zero_or_negative"] += 1
                    continue

                stats["basement_rows"] += 1
                kept[index] = {
                    "gis_building_id": ascii_value("A1"),
                    "pnu": ascii_value("A2"),
                    "legal_dong_code": ascii_value("A3"),
                    "building_use_code": ascii_value("A8"),
                    "building_use_name": korean_value("A9"),
                    "underground_floor_count": underground,
                }
        finally:
            mm.close()
    return kept, stats


def iter_shp_centroids(
    shp_path: Path, wanted: set[int]
) -> Iterator[tuple[int, float, float]]:
    """Yield (record_index, x, y) centroids for the wanted record indexes.

    Shapefile records are positional and align 1:1 with DBF records, so the
    index is the join key.  Only polygon rings are read; the centroid is
    computed from the full ring set so multipart buildings stay correct.
    """
    with shp_path.open("rb") as stream:
        mm = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            size = len(mm)
            offset = 100  # main file header
            index = 0
            while offset + 8 <= size:
                content_length_words = struct.unpack(">I", mm[offset + 4 : offset + 8])[0]
                content_start = offset + 8
                content_end = content_start + content_length_words * 2
                if content_end > size:
                    break

                if index in wanted:
                    shape_type = struct.unpack("<I", mm[content_start : content_start + 4])[0]
                    if shape_type == SHAPE_TYPE_POLYGON:
                        num_parts = struct.unpack(
                            "<I", mm[content_start + 36 : content_start + 40]
                        )[0]
                        num_points = struct.unpack(
                            "<I", mm[content_start + 40 : content_start + 44]
                        )[0]
                        parts_start = content_start + 44
                        points_start = parts_start + num_parts * 4
                        part_offsets = list(
                            struct.unpack(
                                f"<{num_parts}I",
                                mm[parts_start : parts_start + num_parts * 4],
                            )
                        )
                        part_offsets.append(num_points)

                        rings: list[list[tuple[float, float]]] = []
                        for part in range(num_parts):
                            begin, end = part_offsets[part], part_offsets[part + 1]
                            chunk = mm[
                                points_start + begin * 16 : points_start + end * 16
                            ]
                            coords = struct.unpack(f"<{(end - begin) * 2}d", chunk)
                            ring = list(zip(coords[0::2], coords[1::2]))
                            if len(ring) >= 4:
                                rings.append(ring)

                        centroid = centroid_of_rings(rings)
                        if centroid is not None:
                            yield index, centroid[0], centroid[1]
                    elif shape_type != SHAPE_TYPE_NULL:
                        raise OverlapError(
                            f"{shp_path.name} record {index} has unsupported shape type {shape_type}"
                        )

                offset = content_end
                index += 1
        finally:
            mm.close()


def centroid_of_rings(rings: list[list[tuple[float, float]]]) -> tuple[float, float] | None:
    """Build a polygon from the rings and return its representative point.

    ``representative_point`` is used instead of ``centroid`` because a
    building footprint can be concave or ring-shaped, where the true
    centroid may fall outside the footprint.
    """
    if not rings:
        return None
    try:
        outer = rings[0]
        holes = rings[1:] if len(rings) > 1 else None
        geom: Polygon | MultiPolygon = Polygon(outer, holes)
        if not geom.is_valid:
            repaired = make_valid(geom)
            geom = polygonal_only(repaired)
            if geom is None:
                return None
        point = geom.representative_point()
        return point.x, point.y
    except Exception:
        return None


def polygonal_only(geometry):
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if hasattr(geometry, "geoms"):
        parts = [g for g in geometry.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if parts:
            return unary_union(parts)
    return None


def load_province_flood_union(province_code: str) -> tuple[Any, dict[str, int]]:
    """Union every flood polygon recorded for one province."""
    if not FLOOD_GEOJSON.exists():
        raise OverlapError(f"Flood source missing: {FLOOD_GEOJSON}")

    with FLOOD_GEOJSON.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    geoms = []
    stats = {"province_polygons": 0, "invalid_repaired": 0, "dropped": 0}
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        if str(props.get("stdg_ctpv_cd") or "").strip() != province_code:
            continue
        stats["province_polygons"] += 1
        try:
            geom = shape(feature["geometry"])
        except Exception:
            stats["dropped"] += 1
            continue
        if not geom.is_valid:
            geom = polygonal_only(make_valid(geom))
            if geom is None:
                stats["dropped"] += 1
                continue
            stats["invalid_repaired"] += 1
        geoms.append(geom)

    if not geoms:
        return None, stats
    return unary_union(geoms), stats


def analyse(province_code: str, shp_dir: Path) -> dict[str, Any]:
    dbf_paths = sorted(shp_dir.glob("*.dbf"))
    if not dbf_paths:
        raise OverlapError(f"No DBF found under {shp_dir}")

    flood_union, flood_stats = load_province_flood_union(province_code)
    if flood_union is None:
        raise OverlapError(f"No flood polygons for province {province_code}")
    prepared_flood = prep(flood_union)

    # Source is EPSG:5186 for snapshots from 2023-08-08, EPSG:5174 before.
    prj_paths = sorted(shp_dir.glob("*.prj"))
    source_epsg = "5186"
    if prj_paths:
        prj_text = prj_paths[0].read_text(encoding="utf-8", errors="ignore")
        if "5174" in prj_text:
            source_epsg = "5174"
    transformer = Transformer.from_crs(
        f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True
    )

    totals = {
        "basement_buildings": 0,
        "geometry_resolved": 0,
        "geometry_missing": 0,
        "inside_flood_polygon": 0,
    }
    dbf_stats_total: dict[str, int] = {}
    flooded_samples: list[dict[str, Any]] = []
    # Every flooded building is kept, not just a sample: this list is the
    # input the Building HUB collector needs to confirm underground parking.
    flooded_rows: list[dict[str, Any]] = []
    use_counts: Counter[str] = Counter()

    for dbf_path in dbf_paths:
        shp_path = dbf_path.with_suffix(".shp")
        if not shp_path.exists():
            raise OverlapError(f"Missing SHP beside {dbf_path.name}")

        print(f"  [dbf] {dbf_path.name} 읽는 중...", flush=True)
        kept, stats = basement_record_indexes(dbf_path)
        for key, value in stats.items():
            dbf_stats_total[key] = dbf_stats_total.get(key, 0) + value
        totals["basement_buildings"] += len(kept)
        print(
            f"  [dbf] 전체 {stats['dbf_declared_rows']:,}행 중 지하층 보유 {len(kept):,}동",
            flush=True,
        )

        if not kept:
            continue

        print(f"  [shp] {shp_path.name} 좌표 추출 중...", flush=True)
        wanted = set(kept)
        resolved = 0
        for index, x, y in iter_shp_centroids(shp_path, wanted):
            resolved += 1
            lon, lat = transformer.transform(x, y)
            if prepared_flood.contains(Point(lon, lat)):
                totals["inside_flood_polygon"] += 1
                record = dict(kept[index])
                record["longitude"] = round(lon, 7)
                record["latitude"] = round(lat, 7)
                record["source_dbf"] = dbf_path.name
                flooded_rows.append(record)
                use_counts[record["building_use_name"] or "(미기재)"] += 1
                if len(flooded_samples) < 50:
                    flooded_samples.append(record)
        totals["geometry_resolved"] += resolved
        totals["geometry_missing"] += len(wanted) - resolved

    rate = (
        totals["inside_flood_polygon"] / totals["basement_buildings"]
        if totals["basement_buildings"]
        else 0.0
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    flooded_csv = OUT_DIR / f"basement_flood_overlap_{province_code}_flooded.csv"
    fieldnames = [
        "gis_building_id",
        "pnu",
        "legal_dong_code",
        "building_use_code",
        "building_use_name",
        "underground_floor_count",
        "longitude",
        "latitude",
        "source_dbf",
    ]
    with flooded_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(flooded_rows)

    return {
        "flooded_csv": display_path(flooded_csv),
        "building_use_top20": dict(use_counts.most_common(20)),
        "province_code": province_code,
        "province_name": PROVINCE_NAMES.get(province_code, province_code),
        "source_dir": display_path(shp_dir),
        "source_epsg": source_epsg,
        "flood": flood_stats,
        "dbf": dbf_stats_total,
        "totals": totals,
        "inside_rate": round(rate, 6),
        "flooded_samples": flooded_samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--province",
        required=True,
        help="two-digit 법정 시도코드, e.g. 11 for Seoul",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="shapefile directory (defaults to the matching folder under data/raw/vworld-buildings/national)",
    )
    args = parser.parse_args()

    province = args.province.strip()
    shp_dir = args.dir
    if shp_dir is None:
        matches = sorted(RAW_NATIONAL.glob(f"AL_D010_{province}_*"))
        if not matches:
            raise SystemExit(
                f"No shapefile directory for province {province} under {RAW_NATIONAL}"
            )
        shp_dir = matches[-1]

    name = PROVINCE_NAMES.get(province, province)
    print(f"[start] {name}({province}) — {shp_dir.name}", flush=True)

    result = analyse(province, shp_dir)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"basement_flood_overlap_{province}.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    totals = result["totals"]
    print()
    print(f"[결과] {name}({province})")
    print(f"  침수 Polygon        : {result['flood']['province_polygons']:,}건")
    print(f"  지하층 보유 건물     : {totals['basement_buildings']:,}동")
    print(f"  좌표 확인됨          : {totals['geometry_resolved']:,}동")
    print(f"  침수 Polygon 내부    : {totals['inside_flood_polygon']:,}동")
    print(f"  비율                : {result['inside_rate'] * 100:.2f}%")
    print(f"  저장                : {display_path(out_path)}")


if __name__ == "__main__":
    try:
        main()
    except OverlapError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
