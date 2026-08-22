#!/usr/bin/env python3
"""Turn the raw Gyeongbuk building-register collection into an ML feature table.

The collector in download_gyeongbuk_building_register.py produces an 83-column
join of 건축HUB 표제부 + 층별개요 rows keyed by PNU (parcel).  That table cannot
go into a model as-is for three reasons:

1. It has no coordinates, so it cannot be joined to flood polygons or rainfall.
2. PNU is a parcel, not a building, so register rows are many-to-many with
   buildings (up to 285 register rows on one parcel).
3. Most of the 83 columns are permit/energy/roof metadata irrelevant to flooding.

This script fixes all three:

* Row unit becomes one GIS building that itself has 지하층 >= 1 (A27), taken from
  the official VWorld GIS건물통합정보 SHP.
* Coordinates come from the building polygon centroid, converted from
  EPSG:5186 (Korea 2000 Central Belt) to WGS84 lon/lat.
* Register evidence is aggregated to the parcel and attached to each building on
  that parcel, with the parcel-level nature recorded explicitly.

The projection is implemented with the standard Snyder inverse Transverse
Mercator series so the script stays pure-stdlib like the rest of scripts/.
Run verify_projection() to check it against pyproj when that is installed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import mmap
import struct
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from data_paths import (
    INTERIM_BUILDING_REGISTER,
    PROCESSED_BUILDINGS,
    RAW_VWORLD_GYEONGBUK,
    ROOT,
)

GIS_ROOT = RAW_VWORLD_GYEONGBUK
REGISTER_CSV = INTERIM_BUILDING_REGISTER / "gyeongbuk_underground_parking_candidates.csv"
CANDIDATES_CSV = INTERIM_BUILDING_REGISTER / "gyeongbuk_gis_basement_candidates.csv"
OUT_CSV = PROCESSED_BUILDINGS / "gyeongbuk_building_underground_parking_features.csv"
OUT_DIR = ROOT / "outputs/gyeongbuk-building-features"
MANIFEST = OUT_DIR / "manifest.json"
SAMPLE_CSV = OUT_DIR / "gyeongbuk_building_underground_parking_features_sample.csv"

# Strongest evidence first; used to collapse many register rows onto one parcel.
STATUS_RANK = {
    "CONFIRMED_BASEMENT_PARKING_USE": 3,
    "PROBABLE_NOT_CONFIRMED_IN_FLOOR_ROWS": 2,
    "UNDERGROUND_FLOOR_ONLY": 1,
    "GIS_BASEMENT_CANDIDATE_NOT_CONFIRMED_BY_TITLE": 0,
}

# EPSG:5186 -- Korea 2000 / Central Belt 2010, GRS80 ellipsoid.
GRS80_A = 6378137.0
GRS80_INV_F = 298.257222101
TM_LAT0 = math.radians(38.0)
TM_LON0 = math.radians(127.0)
TM_K0 = 1.0
TM_FE = 200000.0
TM_FN = 600000.0


# --------------------------------------------------------------------------
# Inverse Transverse Mercator (Snyder, Map Projections -- A Working Manual)
# --------------------------------------------------------------------------


def _tm_constants() -> tuple[float, float, float]:
    f = 1.0 / GRS80_INV_F
    e2 = 2 * f - f * f
    ep2 = e2 / (1 - e2)
    m0 = _meridional_arc(TM_LAT0, e2)
    return e2, ep2, m0


def _meridional_arc(lat: float, e2: float) -> float:
    e4 = e2 * e2
    e6 = e4 * e2
    return GRS80_A * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lat)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lat)
        - (35 * e6 / 3072) * math.sin(6 * lat)
    )


def tm5186_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convert EPSG:5186 easting/northing (m) to WGS84 (lon, lat) in degrees."""
    e2, ep2, m0 = _tm_constants()
    x = easting - TM_FE
    y = northing - TM_FN

    m = m0 + y / TM_K0
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    mu = m / (GRS80_A * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))

    e1_2, e1_3, e1_4 = e1 * e1, e1**3, e1**4
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1_3 / 32) * math.sin(2 * mu)
        + (21 * e1_2 / 16 - 55 * e1_4 / 32) * math.sin(4 * mu)
        + (151 * e1_3 / 96) * math.sin(6 * mu)
        + (1097 * e1_4 / 512) * math.sin(8 * mu)
    )

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)

    c1 = ep2 * cos_phi1**2
    t1 = tan_phi1**2
    n1 = GRS80_A / math.sqrt(1 - e2 * sin_phi1**2)
    r1 = GRS80_A * (1 - e2) / (1 - e2 * sin_phi1**2) ** 1.5
    d = x / (n1 * TM_K0)

    d2, d3, d4, d5, d6 = d**2, d**3, d**4, d**5, d**6
    lat = phi1 - (n1 * tan_phi1 / r1) * (
        d2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d6 / 720
    )
    lon = TM_LON0 + (
        d
        - (1 + 2 * t1 + c1) * d3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d5 / 120
    ) / cos_phi1

    return math.degrees(lon), math.degrees(lat)


def verify_projection() -> None:
    """Cross-check the stdlib projection against pyproj if it is importable."""
    try:
        from pyproj import Transformer
    except ImportError:
        print("[skip] pyproj not installed; cannot cross-check the projection")
        return
    tf = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)
    samples = [
        (200000.0, 600000.0),
        (296000.0, 380000.0),  # near Pohang
        (170000.0, 420000.0),
        (250000.0, 500000.0),
    ]
    worst = 0.0
    for e, n in samples:
        ours = tm5186_to_wgs84(e, n)
        theirs = tf.transform(e, n)
        dlon = abs(ours[0] - theirs[0]) * 88000  # ~m per degree lon at 36N
        dlat = abs(ours[1] - theirs[1]) * 111000
        worst = max(worst, dlon, dlat)
    print(f"[check] projection max deviation vs pyproj: {worst:.4f} m")
    if worst > 0.5:
        raise SystemExit("projection disagrees with pyproj by more than 0.5 m")


# --------------------------------------------------------------------------
# DBF / SHP readers (pure stdlib)
# --------------------------------------------------------------------------


def latest_gis_dir() -> Path:
    dirs = {
        directory
        for pattern in ("AL_D010_47_*", "AL_47_D010_*")
        for directory in GIS_ROOT.glob(pattern)
        if directory.is_dir() and any(directory.glob("*.dbf"))
    }
    if not dirs:
        raise SystemExit(f"No Gyeongbuk GIS-building directory with DBF files under {GIS_ROOT}")
    return max(dirs, key=lambda path: path.name.rsplit("_", 1)[-1])


def dbf_layout(path: Path):
    with path.open("rb") as fh:
        header = fh.read(32)
        row_count = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]
        fields = {}
        offset = 1
        fh.seek(32)
        while True:
            raw = fh.read(32)
            if not raw or raw[0:1] == b"\r":
                break
            name = raw[0:11].split(b"\x00")[0].decode("cp949", errors="ignore")
            length = raw[16]
            fields[name] = (offset, length)
            offset += length
    return row_count, header_length, record_length, fields


def read_polygon_centroid(shp: mmap.mmap, offset: int) -> tuple[float, float, float] | None:
    """Return (centroid_x, centroid_y, area_m2) of the largest ring, or None."""
    shape_type = struct.unpack_from("<i", shp, offset + 8)[0]
    if shape_type != 5:  # not a polygon
        return None
    base = offset + 12
    num_parts, num_points = struct.unpack_from("<ii", shp, base + 32)
    if num_parts < 1 or num_points < 4:
        return None
    parts_off = base + 40
    points_off = parts_off + 4 * num_parts
    parts = list(struct.unpack_from(f"<{num_parts}i", shp, parts_off)) + [num_points]

    best = None
    for i in range(num_parts):
        start, end = parts[i], parts[i + 1]
        n = end - start
        if n < 4:
            continue
        coords = struct.unpack_from(f"<{2 * n}d", shp, points_off + start * 16)
        a2 = cx = cy = 0.0
        for j in range(n - 1):
            x0, y0 = coords[2 * j], coords[2 * j + 1]
            x1, y1 = coords[2 * j + 2], coords[2 * j + 3]
            cross = x0 * y1 - x1 * y0
            a2 += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if abs(a2) < 1e-12:
            continue
        area = abs(a2) / 2.0
        if best is None or area > best[2]:
            best = (cx / (3.0 * a2), cy / (3.0 * a2), area)
    return best


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def to_number(value: str):
    if value in ("", None):
        return None
    try:
        n = float(value)
    except ValueError:
        return None
    return n


def aggregate_register_by_pnu() -> tuple[dict, dict]:
    rows = list(csv.DictReader(REGISTER_CSV.open(encoding="utf-8-sig")))
    print(f"[check] read {len(rows):,} register rows from {REGISTER_CSV.name}")

    by_pnu: dict[str, dict] = {}
    for r in rows:
        pnu = r.get("pnu", "").strip()
        if not pnu:
            continue
        status = r.get("underground_parking_status", "")
        agg = by_pnu.setdefault(
            pnu,
            {
                "register_row_count": 0,
                "status": status,
                "status_rank": -1,
                "evidence": r.get("underground_parking_evidence", ""),
                "ugrnd_max": None,
                "grnd_max": None,
                "indoor_parking_max": None,
                "tot_area_max": None,
                "arch_area_max": None,
                "plat_area_max": None,
                "height_max": None,
                "household_max": None,
                "purpose_by_area": ("", -1.0),
                "structure_by_area": ("", -1.0),
                "approval_days": [],
            },
        )
        agg["register_row_count"] += 1

        rank = STATUS_RANK.get(status, -1)
        if rank > agg["status_rank"]:
            agg["status_rank"] = rank
            agg["status"] = status
            agg["evidence"] = r.get("underground_parking_evidence", "")

        def bump(key: str, col: str):
            n = to_number(r.get(col, ""))
            if n is not None and (agg[key] is None or n > agg[key]):
                agg[key] = n

        bump("ugrnd_max", "ugrndFlrCnt")
        bump("grnd_max", "grndFlrCnt")
        bump("tot_area_max", "totArea")
        bump("arch_area_max", "archArea")
        bump("plat_area_max", "platArea")
        bump("height_max", "heit")
        bump("household_max", "hhldCnt")

        indoor = sum(
            to_number(r.get(c, "")) or 0.0 for c in ("indrMechUtcnt", "indrAutoUtcnt")
        )
        if agg["indoor_parking_max"] is None or indoor > agg["indoor_parking_max"]:
            agg["indoor_parking_max"] = indoor

        area = to_number(r.get("totArea", "")) or 0.0
        if area > agg["purpose_by_area"][1]:
            agg["purpose_by_area"] = (r.get("mainPurpsCdNm", ""), area)
        if area > agg["structure_by_area"][1]:
            agg["structure_by_area"] = (r.get("strctCdNm", ""), area)

        day = r.get("useAprDay", "").strip()
        if day.isdigit() and len(day) == 8:
            agg["approval_days"].append(day)

    stats = {
        "register_rows": len(rows),
        "register_parcels": len(by_pnu),
        "status_counts": dict(Counter(r.get("underground_parking_status", "") for r in rows)),
    }
    print(f"[check] aggregated to {len(by_pnu):,} parcels (PNU)")
    return by_pnu, stats


def main() -> None:
    verify_projection()

    by_pnu, reg_stats = aggregate_register_by_pnu()

    candidates = list(csv.DictReader(CANDIDATES_CSV.open(encoding="utf-8-sig")))
    wanted_ids = {c["gis_building_id"] for c in candidates}
    print(f"[check] {len(candidates):,} GIS basement-candidate buildings to locate")

    gis_dir = latest_gis_dir()
    print(f"[check] reading geometry from {gis_dir.name}")

    located: dict[str, dict] = {}
    no_geom = 0
    for dbf_path in sorted(gis_dir.glob("*.dbf")):
        shp_path = dbf_path.with_suffix(".shp")
        shx_path = dbf_path.with_suffix(".shx")
        if not shp_path.exists() or not shx_path.exists():
            print(f"[warn] {dbf_path.name} has no matching .shp/.shx; skipped")
            continue

        row_count, header_length, record_length, fields = dbf_layout(dbf_path)
        id_off, id_len = fields["A1"]
        pnu_off, pnu_len = fields["A2"]

        with shx_path.open("rb") as fh:
            shx = fh.read()

        with dbf_path.open("rb") as dfh, shp_path.open("rb") as sfh:
            dbf = mmap.mmap(dfh.fileno(), 0, access=mmap.ACCESS_READ)
            shp = mmap.mmap(sfh.fileno(), 0, access=mmap.ACCESS_READ)
            hits = 0
            for i in range(row_count):
                rec = header_length + i * record_length
                gid = dbf[rec + id_off : rec + id_off + id_len].decode("ascii", "ignore").strip()
                if gid not in wanted_ids or gid in located:
                    continue
                pnu = dbf[rec + pnu_off : rec + pnu_off + pnu_len].decode("ascii", "ignore").strip()
                shx_rec = 100 + i * 8
                if shx_rec + 8 > len(shx):
                    continue
                shp_offset = struct.unpack_from(">i", shx, shx_rec)[0] * 2
                geom = read_polygon_centroid(shp, shp_offset)
                if geom is None:
                    no_geom += 1
                    continue
                cx, cy, area = geom
                lon, lat = tm5186_to_wgs84(cx, cy)
                located[gid] = {
                    "pnu": pnu,
                    "longitude": round(lon, 7),
                    "latitude": round(lat, 7),
                    "footprint_area_m2": round(area, 1),
                }
                hits += 1
            dbf.close()
            shp.close()
        print(f"[progress] {dbf_path.name}: matched {hits:,} of {row_count:,} records")

    print(f"[check] located {len(located):,} / {len(candidates):,} candidate buildings")
    if no_geom:
        print(f"[warn] {no_geom} records had unusable geometry")

    # ---- assemble the feature table -------------------------------------
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "building_id",
        "pnu",
        "longitude",
        "latitude",
        "footprint_area_m2",
        "sigungu_code",
        "legal_dong_name",
        "lot_number",
        "building_name",
        "gis_use_name",
        "underground_floor_count_gis",
        "ground_floor_count_gis",
        "underground_parking_status",
        "underground_parking_confirmed",
        "register_underground_floor_max",
        "register_ground_floor_max",
        "indoor_parking_slots_max",
        "total_floor_area_max_m2",
        "building_area_max_m2",
        "parcel_area_max_m2",
        "building_height_max_m",
        "household_count_max",
        "main_purpose_name",
        "structure_name",
        "approval_year_min",
        "register_rows_on_parcel",
        "register_evidence",
    ]

    written = 0
    unmatched_register = 0
    status_out = Counter()
    seen = set()
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for c in candidates:
            gid = c["gis_building_id"]
            if gid in seen:
                continue
            seen.add(gid)
            geo = located.get(gid)
            if geo is None:
                continue
            pnu = geo["pnu"] or c["pnu"]
            agg = by_pnu.get(pnu)
            if agg is None:
                unmatched_register += 1
                agg = {
                    "register_row_count": 0,
                    "status": "GIS_ONLY_NO_REGISTER_ROW",
                    "evidence": "",
                    "ugrnd_max": None,
                    "grnd_max": None,
                    "indoor_parking_max": None,
                    "tot_area_max": None,
                    "arch_area_max": None,
                    "plat_area_max": None,
                    "height_max": None,
                    "household_max": None,
                    "purpose_by_area": ("", -1.0),
                    "structure_by_area": ("", -1.0),
                    "approval_days": [],
                }
            status = agg["status"]
            status_out[status] += 1
            days = agg["approval_days"]
            writer.writerow(
                [
                    gid,
                    pnu,
                    geo["longitude"],
                    geo["latitude"],
                    geo["footprint_area_m2"],
                    pnu[:5],
                    c.get("legal_dong_name", ""),
                    c.get("lot_number", ""),
                    c.get("building_name", ""),
                    c.get("building_use_name", ""),
                    c.get("underground_floor_count_gis", ""),
                    c.get("ground_floor_count_gis", ""),
                    status,
                    1 if status == "CONFIRMED_BASEMENT_PARKING_USE" else 0,
                    agg["ugrnd_max"] if agg["ugrnd_max"] is not None else "",
                    agg["grnd_max"] if agg["grnd_max"] is not None else "",
                    agg["indoor_parking_max"] if agg["indoor_parking_max"] is not None else "",
                    agg["tot_area_max"] if agg["tot_area_max"] is not None else "",
                    agg["arch_area_max"] if agg["arch_area_max"] is not None else "",
                    agg["plat_area_max"] if agg["plat_area_max"] is not None else "",
                    agg["height_max"] if agg["height_max"] is not None else "",
                    agg["household_max"] if agg["household_max"] is not None else "",
                    agg["purpose_by_area"][0],
                    agg["structure_by_area"][0],
                    min(days)[:4] if days else "",
                    agg["register_row_count"],
                    agg["evidence"],
                ]
            )
            written += 1

    print(f"[check] wrote {OUT_CSV.relative_to(ROOT)} ({written:,} buildings)")
    print("[check] underground parking status distribution:")
    for k, v in status_out.most_common():
        print(f"          {v:6,}  {k}")
    if unmatched_register:
        print(f"[warn] {unmatched_register} buildings had no register row on their parcel")

    # ---- sample + manifest ----------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open(encoding="utf-8") as src, SAMPLE_CSV.open("w", encoding="utf-8") as dst:
        for i, line in enumerate(src):
            if i > 500:
                break
            dst.write(line)

    digest = hashlib.sha256(OUT_CSV.read_bytes()).hexdigest()
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "row_unit": "one GIS building whose own GIS attribute A27 (지하층수) is >= 1",
        "row_count": written,
        "crs": "WGS84 (EPSG:4326), converted from source EPSG:5186",
        "sources": {
            "geometry": f"{gis_dir.relative_to(ROOT)} (VWorld, EPSG:5186)",
            "register": str(REGISTER_CSV.relative_to(ROOT)),
        },
        "register_input": reg_stats,
        "underground_parking_status_counts": dict(status_out),
        "buildings_located": len(located),
        "buildings_requested": len(candidates),
        "outputs": {str(OUT_CSV.relative_to(ROOT)): {"sha256": digest}},
        "critical_limitations": [
            "underground_parking_status is derived at PARCEL (PNU) level, not per building. "
            "A parcel with several buildings gives them all the same status.",
            "Only buildings whose own GIS 지하층수 >= 1 are included, so this is not every "
            "Gyeongbuk building and cannot supply negative examples on its own.",
            "A status other than CONFIRMED does not mean there is no underground parking; "
            "it means the floor-detail rows did not state a parking use.",
            "Coordinates are polygon centroids of the building footprint, not surveyed points.",
            "No flood label and no rainfall are attached here; join separately by location.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[check] wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    if "--verify-projection" in sys.argv:
        verify_projection()
    else:
        main()
