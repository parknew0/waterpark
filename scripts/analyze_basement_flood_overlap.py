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
import re
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
    "12": "전남광주통합특별시",
    "26": "부산광역시",
    "27": "대구광역시",
    "28": "인천광역시",
    "29": "광주광역시",
    "30": "대전광역시",
    "31": "울산광역시",
    "36": "세종특별자치시",
    "41": "경기도",
    "42": "강원도",
    "43": "충청북도",
    "44": "충청남도",
    "45": "전라북도",
    "46": "전라남도",
    "47": "경상북도",
    "48": "경상남도",
    "50": "제주특별자치도",
    "51": "강원특별자치도",
    "52": "전북특별자치도",
}

# The 2026 building snapshots use post-reorganisation province codes, while the
# 2002-2022 flood traces still carry the codes that were current when each
# survey was filed.  Mapping them is required or three provinces silently
# produce zero flood polygons.
#
#   강원도 42        -> 강원특별자치도 51   (2023-06-11)
#   전라북도 45      -> 전북특별자치도 52   (2024-01-18)
#   광주 29 + 전남 46 -> 전남광주통합특별시 12
BUILDING_TO_FLOOD_PROVINCES = {
    "12": ["29", "46"],
    "51": ["42"],
    "52": ["45"],
}


def flood_codes_for(province_code: str) -> list[str]:
    """Flood-trace province codes that cover one building-snapshot province."""
    return BUILDING_TO_FLOOD_PROVINCES.get(province_code, [province_code])


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


def approval_year(value: str) -> int | None:
    """Year from A13 사용승인일자, which appears as YYYYMMDD or YYYY-MM-DD."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 4:
        return None
    year = int(digits[:4])
    return year if 1800 <= year <= 2100 else None


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
    required = {"A1", "A2", "A3", "A8", "A9", "A13", "A27"}
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
                    "approval_date": ascii_value("A13"),
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


def flood_year(props: dict[str, Any]) -> int | None:
    """Best available event year for one flood polygon.

    ``fldn_bgng_ymd`` is preferred because it is the surveyed start date.
    ``fldn_yr`` is the fallback, except for the literal 0 that the Esri
    export uses for the source's ``외`` value, which is not a real year.
    """
    ymd = str(props.get("fldn_bgng_ymd") or "").strip()
    if len(ymd) >= 4 and ymd[:4].isdigit():
        year = int(ymd[:4])
        if 1900 <= year <= 2100:
            return year
    raw_year = str(props.get("fldn_yr") or "").strip()
    if raw_year.isdigit():
        year = int(raw_year)
        if 1900 <= year <= 2100:
            return year
    return None


def load_province_floods(
    province_code: str,
) -> tuple[Any, list[Any], list[int | None], dict[str, Any]]:
    """Flood polygons for one province, as a union and as indexed parts.

    The union drives the inside/outside decision.  The individual polygons
    and their years are kept alongside so a flooded building can be dated
    against the specific events that cover it.
    """
    if not FLOOD_GEOJSON.exists():
        raise OverlapError(f"Flood source missing: {FLOOD_GEOJSON}")

    with FLOOD_GEOJSON.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    wanted_codes = set(flood_codes_for(province_code))
    geoms: list[Any] = []
    years: list[int | None] = []
    stats: dict[str, Any] = {
        "province_polygons": 0,
        "invalid_repaired": 0,
        "dropped": 0,
        "polygons_without_year": 0,
        "flood_province_codes": sorted(wanted_codes),
        "polygons_by_flood_code": {},
        "flood_year_range": [],
    }
    per_code: Counter[str] = Counter()
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        code = str(props.get("stdg_ctpv_cd") or "").strip()
        if code not in wanted_codes:
            continue
        stats["province_polygons"] += 1
        per_code[code] += 1
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
        year = flood_year(props)
        if year is None:
            stats["polygons_without_year"] += 1
        geoms.append(geom)
        years.append(year)

    stats["polygons_by_flood_code"] = dict(sorted(per_code.items()))
    known_years = [y for y in years if y is not None]
    if known_years:
        stats["flood_year_range"] = [min(known_years), max(known_years)]
    if not geoms:
        return None, [], [], stats
    return unary_union(geoms), geoms, years, stats


def analyse(province_code: str, shp_dir: Path) -> dict[str, Any]:
    dbf_paths = sorted(shp_dir.glob("*.dbf"))
    if not dbf_paths:
        raise OverlapError(f"No DBF found under {shp_dir}")

    flood_union, flood_parts, flood_years, flood_stats = load_province_floods(
        province_code
    )
    if flood_union is None:
        raise OverlapError(f"No flood polygons for province {province_code}")
    prepared_flood = prep(flood_union)
    # Individual polygons stay indexed so a flooded building can be dated
    # against the specific events covering it, not just the province range.
    flood_tree = STRtree(flood_parts)
    prepared_parts = [prep(part) for part in flood_parts]

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
    # Timeline check: a 2026 snapshot can contain buildings that did not
    # exist when the flood was surveyed.
    age = {
        "approval_date_missing": 0,
        "approval_year_unparsed": 0,
        "flood_year_unknown": 0,
        "approved_after_last_flood": 0,
        "approved_after_first_flood": 0,
        "approved_before_or_same_year": 0,
    }
    approval_years: Counter[int] = Counter()

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
            point = Point(lon, lat)
            if prepared_flood.contains(point):
                totals["inside_flood_polygon"] += 1
                record = dict(kept[index])
                record["longitude"] = round(lon, 7)
                record["latitude"] = round(lat, 7)
                record["source_dbf"] = dbf_path.name

                covering = [
                    flood_years[i]
                    for i in flood_tree.query(point)
                    if prepared_parts[i].contains(point)
                ]
                known = [year for year in covering if year is not None]
                last_flood = max(known) if known else None
                first_flood = min(known) if known else None
                record["last_flood_year"] = last_flood if last_flood else ""
                record["first_flood_year"] = first_flood if first_flood else ""

                approved = approval_year(record["approval_date"])
                record["approval_year"] = approved if approved else ""
                if approved:
                    approval_years[approved] += 1
                if not record["approval_date"]:
                    age["approval_date_missing"] += 1
                elif approved is None:
                    age["approval_year_unparsed"] += 1
                elif last_flood is None:
                    age["flood_year_unknown"] += 1
                elif approved > last_flood:
                    # Newer than every event covering it: it cannot have been
                    # flooded by any of them.
                    age["approved_after_last_flood"] += 1
                    record["existed_at_flood"] = "NO"
                else:
                    age["approved_before_or_same_year"] += 1
                    record["existed_at_flood"] = "YES"
                    if first_flood is not None and approved > first_flood:
                        # Existed for the later events but not the earliest,
                        # so a per-event table must drop those earlier rows.
                        age["approved_after_first_flood"] += 1
                        record["existed_at_flood"] = "PARTIAL"
                record.setdefault("existed_at_flood", "UNKNOWN")

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
        "approval_date",
        "approval_year",
        "first_flood_year",
        "last_flood_year",
        "existed_at_flood",
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
        "timeline": age,
        "approval_year_histogram": dict(sorted(approval_years.items())),
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


def run_one(province: str, shp_dir: Path) -> dict[str, Any]:
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
    codes = "+".join(result["flood"]["flood_province_codes"])
    print()
    print(f"[결과] {name}({province})")
    print(f"  침수 Polygon        : {result['flood']['province_polygons']:,}건 (시도코드 {codes})")
    print(f"  지하층 보유 건물     : {totals['basement_buildings']:,}동")
    print(f"  좌표 확인됨          : {totals['geometry_resolved']:,}동")
    print(f"  침수 Polygon 내부    : {totals['inside_flood_polygon']:,}동")
    print(f"  비율                : {result['inside_rate'] * 100:.2f}%")
    age = result["timeline"]
    checked = age["approved_after_last_flood"] + age["approved_before_or_same_year"]
    if checked:
        after = age["approved_after_last_flood"]
        print(
            f"  사건 후 준공(제외대상): {after:,}동 / 판정가능 {checked:,}동"
            f" ({after / checked * 100:.1f}%)"
        )
    print(f"  저장                : {display_path(out_path)}")
    print(flush=True)
    return result


def discover_provinces() -> list[tuple[str, Path]]:
    """Every downloaded national snapshot, newest snapshot per province."""
    latest: dict[str, Path] = {}
    for directory in sorted(RAW_NATIONAL.glob("AL_D010_*")):
        if not directory.is_dir():
            continue
        match = re.match(r"AL_D010_(\d{2})_(20\d{6})$", directory.name)
        if not match:
            continue
        latest[match.group(1)] = directory
    return sorted(latest.items())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--province",
        help="two-digit 법정 시도코드, e.g. 11 for Seoul",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="run every downloaded province under data/raw/vworld-buildings/national",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="shapefile directory (defaults to the matching folder under data/raw/vworld-buildings/national)",
    )
    args = parser.parse_args()

    if not args.all and not args.province:
        raise SystemExit("Pass --province <코드> or --all")

    if args.all:
        targets = discover_provinces()
        if not targets:
            raise SystemExit(f"No snapshots found under {RAW_NATIONAL}")
        print(f"[plan] {len(targets)}개 시도 처리: {', '.join(c for c, _ in targets)}\n")
        results: list[dict[str, Any]] = []
        failures: list[tuple[str, str]] = []
        for province, shp_dir in targets:
            try:
                results.append(run_one(province, shp_dir))
            except OverlapError as exc:
                failures.append((province, str(exc)))
                print(f"[skip] {province}: {exc}\n", flush=True)
        print_summary(results, failures)
        return

    province = args.province.strip()
    shp_dir = args.dir
    if shp_dir is None:
        matches = sorted(RAW_NATIONAL.glob(f"AL_D010_{province}_*"))
        if not matches:
            raise SystemExit(
                f"No shapefile directory for province {province} under {RAW_NATIONAL}"
            )
        shp_dir = matches[-1]
    run_one(province, shp_dir)


def print_summary(
    results: list[dict[str, Any]], failures: list[tuple[str, str]]
) -> None:
    ordered = sorted(
        results, key=lambda r: r["totals"]["inside_flood_polygon"], reverse=True
    )
    print("=" * 72)
    print(f"{'시도':<20}{'침수Poly':>9}{'지하층건물':>11}{'침수내부':>9}{'비율':>8}")
    print("-" * 72)
    for result in ordered:
        totals = result["totals"]
        print(
            f"{result['province_name']:<20}"
            f"{result['flood']['province_polygons']:>9,}"
            f"{totals['basement_buildings']:>11,}"
            f"{totals['inside_flood_polygon']:>9,}"
            f"{result['inside_rate'] * 100:>7.2f}%"
        )
    print("-" * 72)
    total_basement = sum(r["totals"]["basement_buildings"] for r in ordered)
    total_inside = sum(r["totals"]["inside_flood_polygon"] for r in ordered)
    rate = total_inside / total_basement * 100 if total_basement else 0.0
    print(
        f"{'전국 합계':<20}"
        f"{sum(r['flood']['province_polygons'] for r in ordered):>9,}"
        f"{total_basement:>11,}"
        f"{total_inside:>9,}"
        f"{rate:>7.2f}%"
    )
    print("=" * 72)
    if failures:
        print("\n[처리 실패]")
        for province, message in failures:
            print(f"  {province}: {message}")


if __name__ == "__main__":
    try:
        main()
    except OverlapError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
