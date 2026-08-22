#!/usr/bin/env python3
"""Build the surface-flood training table for Waterpark.

Why this exists
---------------
The original target -- "will this underground car park flood" -- cannot be
trained. Only 9 buildings with confirmed underground parking sit inside a flood
polygon, because 침수흔적도 mostly surveyed farmland and river plains while
underground parking is urban. See docs/research-log.md.

So this builds the achievable target instead: **was this building point inside
an officially surveyed surface-flood polygon during this rainfall event**. The
trained model becomes one input to the underground-parking risk score rather
than the whole answer.

The negative-label rule
-----------------------
A building outside a flood polygon is NOT automatically "did not flood" -- it may
simply never have been surveyed. docs/02 section 3.3 forbids that shortcut. So a
building only becomes a weak pseudo-negative when it sits within
NEGATIVE_RADIUS_M of a polygon surveyed in that same event. Everything further
away is dropped as unknown rather than labelled 0.

Row unit: one building x one flood event.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

from data_paths import (
    PROCESSED_BUILDINGS,
    PROCESSED_ML_TRAINING,
    PROCESSED_RAINFALL,
    RAW_FLOOD_TRACE,
    RAW_KMA_STATIONS,
    ROOT,
)

FLOOD_GEOJSON = RAW_FLOOD_TRACE / "gyeongbuk_flood_2002_2022.geojson"
BUILDINGS_GZ = PROCESSED_BUILDINGS / "gyeongbuk_buildings_elevation.csv.gz"
EVENT_RAIN_CSV = PROCESSED_RAINFALL / "gyeongbuk_flood_event_rain.csv"
STATION_CSV = RAW_KMA_STATIONS / "kma_station_list.csv"

OUT_CSV = PROCESSED_ML_TRAINING / "gyeongbuk_flood_training_table.csv"
OUT_DIR = ROOT / "outputs/gyeongbuk-flood-model"
MANIFEST = OUT_DIR / "training_table_manifest.json"

# A building this close to a surveyed flood polygon is treated as a weak
# pseudo-negative. It is not a verified non-flood observation.
NEGATIVE_RADIUS_M = 1000.0
DEG = 1.0 / 111000.0  # rough metres -> degrees, fine at this latitude
MAX_STATION_DISTANCE_KM = 30.0


def log(msg: str) -> None:
    print(msg, flush=True)


def clean_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def normalized_date(value: object) -> str:
    text = clean_text(value)
    if text.isdigit() and len(text) <= 8:
        return text.zfill(8)
    return text


def normalized_time(value: object) -> str:
    text = clean_text(value)
    if text.isdigit() and len(text) <= 4:
        return text.zfill(4)
    return text


def polygonal_only(geometry):
    """Discard non-area remnants returned by make_valid."""
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection) or hasattr(geometry, "geoms"):
        parts = []
        for child in geometry.geoms:
            area = polygonal_only(child)
            if area is not None and not area.is_empty:
                parts.append(area)
        return unary_union(parts) if parts else None
    return None


def prepare_source_polygon(raw_geometry):
    """Validate source geometry before any union, buffer, or distance operation."""
    was_invalid = not raw_geometry.is_valid
    candidate = make_valid(raw_geometry) if was_invalid else raw_geometry
    candidate = polygonal_only(candidate)
    if candidate is None or candidate.is_empty:
        return None, was_invalid, False
    if not candidate.is_valid:
        candidate = polygonal_only(make_valid(candidate))
    usable = candidate is not None and not candidate.is_empty and candidate.is_valid
    return (candidate if usable else None), was_invalid, was_invalid and usable


# ---------------------------------------------------------------- stations


def load_stations() -> list[dict]:
    """Station history rows: id, lat, lon, and the period the site was active."""
    stations = []
    with STATION_CSV.open(encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 8 or not row[0].strip().isdigit():
                continue
            try:
                lat, lon = float(row[6]), float(row[7])
            except ValueError:
                continue
            if not (32 < lat < 40 and 124 < lon < 132):
                continue
            stations.append(
                {
                    "id": row[0].strip(),
                    "start": row[1].strip(),
                    "end": row[2].strip(),
                    "name": row[3].strip(),
                    "lat": lat,
                    "lon": lon,
                }
            )
    log(f"[check] loaded {len(stations):,} station history rows")
    return stations


def stations_active_on(stations: list[dict], ymd: str) -> dict[str, tuple[float, float]]:
    """Latest known position of each station that was operating on that date."""
    day = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    active: dict[str, tuple[float, float]] = {}
    for s in stations:
        if s["start"] and s["start"] > day:
            continue
        if s["end"] and s["end"] < day:
            continue
        active[s["id"]] = (s["lon"], s["lat"])
    return active


def load_event_rain() -> dict[tuple[str, str], dict[str, dict]]:
    """(ymd, tm) -> station_id -> rain values."""
    rain: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    with EVENT_RAIN_CSV.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (
                normalized_date(r.get("fldn_bgng_ymd")),
                normalized_time(r.get("fldn_bgng_tm")),
            )
            rain[key][r["station_id"]] = {
                "event_id": r.get("event_id", ""),
                "storm_group_id": r.get("storm_group_id", ""),
                "rain_1h": r["rain_1h"],
                "rain_3h": r["rain_3h"],
                "rain_6h": r["rain_6h"],
                "rain_12h": r["rain_12h"],
                "rain_24h": r["rain_24h"],
                "hours_available_1h": r.get("hours_available_1h", ""),
                "hours_available_3h": r.get("hours_available_3h", ""),
                "hours_available_6h": r.get("hours_available_6h", ""),
                "hours_available_12h": r.get("hours_available_12h", ""),
                "hours_available_24h": r.get("hours_available_24h", ""),
            }
    log(f"[check] loaded rainfall for {len(rain)} events")
    return rain


# ---------------------------------------------------------------- buildings


def load_buildings() -> tuple[list[dict], list[Point]]:
    rows, pts = [], []
    with gzip.open(BUILDINGS_GZ, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                lon = float(r["longitude"])
                lat = float(r["latitude"])
            except (KeyError, ValueError, TypeError):
                continue
            rows.append(
                {
                    "building_id": r.get("building_id") or r.get("﻿building_id", ""),
                    "city_county": r.get("city_county", ""),
                    "lon": lon,
                    "lat": lat,
                    "elev": r.get("surface_elevation_m", ""),
                    "rel_elev": r.get("relative_elevation_to_local_building_min_m", ""),
                    "local_min": r.get("local_approx_1km_min_surface_elevation_m", ""),
                }
            )
            pts.append(Point(lon, lat))
    log(f"[check] loaded {len(rows):,} Gyeongbuk buildings with elevation")
    return rows, pts


def main() -> None:
    for path in (FLOOD_GEOJSON, BUILDINGS_GZ, EVENT_RAIN_CSV, STATION_CSV):
        if not path.exists():
            raise SystemExit(f"missing input: {path}")

    feats = json.loads(FLOOD_GEOJSON.read_text(encoding="utf-8"))["features"]
    events: dict[tuple[str, str], list] = defaultdict(list)
    event_props: dict[tuple[str, str], dict] = {}
    event_geometry_repaired: dict[tuple[str, str], bool] = defaultdict(bool)
    geometry_stats = {
        "source_feature_count": len(feats),
        "source_parse_failed": 0,
        "source_invalid": 0,
        "source_invalid_repaired": 0,
        "source_dropped_empty_or_nonpolygon": 0,
        "event_union_repaired": 0,
    }
    for f in feats:
        p = f["properties"]
        key = (
            normalized_date(p.get("fldn_bgng_ymd")),
            normalized_time(p.get("fldn_bgng_tm")),
        )
        try:
            raw_geometry = shape(f["geometry"])
        except (KeyError, TypeError, ValueError):
            geometry_stats["source_parse_failed"] += 1
            continue
        geometry, was_invalid, repaired = prepare_source_polygon(raw_geometry)
        if was_invalid:
            geometry_stats["source_invalid"] += 1
        if repaired:
            geometry_stats["source_invalid_repaired"] += 1
            event_geometry_repaired[key] = True
        if geometry is None:
            geometry_stats["source_dropped_empty_or_nonpolygon"] += 1
            continue
        events[key].append(geometry)
        event_props.setdefault(key, p)
    log(f"[check] {len(feats):,} flood polygons in {len(events)} events")

    buildings, points = load_buildings()
    tree = STRtree(points)
    stations = load_stations()
    event_rain = load_event_rain()

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "building_id",
        "event_id",
        "storm_group_id",
        "event_date",
        "event_hour",
        "disaster_name",
        "city_county",
        "longitude",
        "latitude",
        "surface_elevation_m",
        "relative_elevation_m",
        "local_min_elevation_m",
        "distance_to_flood_polygon_m",
        "rain_1h",
        "rain_3h",
        "rain_6h",
        "rain_12h",
        "rain_24h",
        "hours_available_1h",
        "hours_available_3h",
        "hours_available_6h",
        "hours_available_12h",
        "hours_available_24h",
        "rain_station_id",
        "rain_station_distance_km",
        "label_source",
        "label_quality",
        "flood_geometry_repaired",
        "flood",
    ]

    per_event_stats = []
    written = 0
    no_rain = 0

    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)

        for key in sorted(events):
            ymd, tm = key
            polys = events[key]
            rain_for_event = event_rain.get(key, {})
            example_rain = next(iter(rain_for_event.values()), None)
            event_id = example_rain["event_id"] if example_rain else f"GB-{ymd}-{tm}"
            storm_group_id = example_rain["storm_group_id"] if example_rain else ""
            union = unary_union(polys)
            if not union.is_valid:
                repaired_union = polygonal_only(make_valid(union))
                if repaired_union is None or not repaired_union.is_valid:
                    log(f"[warn] {ymd} {tm}: event union is unusable; event skipped")
                    continue
                union = repaired_union
                event_geometry_repaired[key] = True
                geometry_stats["event_union_repaired"] += 1
            buffered = union.buffer(NEGATIVE_RADIUS_M * DEG)
            p_union = prep(union)
            p_buffer = prep(buffered)

            # Candidate buildings: bbox query, then a real containment test.
            candidates = [i for i in tree.query(buffered) if p_buffer.contains(points[i])]
            if not candidates:
                per_event_stats.append(
                    {
                        "event": event_id,
                        "storm_group_id": storm_group_id,
                        "positive": 0,
                        "pseudo_negative": 0,
                        "flood_geometry_repaired": event_geometry_repaired[key],
                    }
                )
                continue

            # Rain: pick the nearest station that actually reported this event.
            active = stations_active_on(stations, ymd)
            usable = [
                (sid, lonlat)
                for sid, lonlat in active.items()
                if sid in rain_for_event
                and clean_text(rain_for_event[sid]["rain_24h"])
                and clean_text(rain_for_event[sid]["hours_available_24h"]) == "24"
            ]
            if not usable:
                no_rain += 1
                log(f"[warn] {ymd} {tm}: no station with rainfall; event skipped")
                per_event_stats.append(
                    {
                        "event": event_id,
                        "storm_group_id": storm_group_id,
                        "positive": 0,
                        "pseudo_negative": 0,
                        "flood_geometry_repaired": event_geometry_repaired[key],
                    }
                )
                continue
            st_ids = [s[0] for s in usable]
            st_xy = np.array([[s[1][0], s[1][1]] for s in usable])

            pos = neg = 0
            for i in candidates:
                pt = points[i]
                inside = p_union.contains(pt)
                b = buildings[i]

                # Distance to the flood polygon, in metres.
                dist_m = 0.0 if inside else union.distance(pt) / DEG

                dx = (st_xy[:, 0] - b["lon"]) * 88.8  # km per degree lon at ~36N
                dy = (st_xy[:, 1] - b["lat"]) * 111.0
                d = np.sqrt(dx * dx + dy * dy)
                j = int(np.argmin(d))
                if d[j] > MAX_STATION_DISTANCE_KM:
                    continue
                rain = rain_for_event[st_ids[j]]
                if inside:
                    label_source = "mois_flood_trace_polygon"
                    label_quality = "observed_polygon_positive"
                else:
                    label_source = "pseudo_negative_1km"
                    label_quality = "pseudo_negative_1km"

                writer.writerow(
                    [
                        b["building_id"],
                        rain["event_id"],
                        rain["storm_group_id"],
                        f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
                        tm[:2],
                        event_props[key].get("fldn_dst_nm", ""),
                        b["city_county"],
                        round(b["lon"], 7),
                        round(b["lat"], 7),
                        b["elev"],
                        b["rel_elev"],
                        b["local_min"],
                        round(dist_m, 1),
                        rain["rain_1h"],
                        rain["rain_3h"],
                        rain["rain_6h"],
                        rain["rain_12h"],
                        rain["rain_24h"],
                        rain["hours_available_1h"],
                        rain["hours_available_3h"],
                        rain["hours_available_6h"],
                        rain["hours_available_12h"],
                        rain["hours_available_24h"],
                        st_ids[j],
                        round(float(d[j]), 2),
                        label_source,
                        label_quality,
                        1 if event_geometry_repaired[key] else 0,
                        1 if inside else 0,
                    ]
                )
                written += 1
                pos += inside
                neg += not inside

            per_event_stats.append(
                {
                    "event": event_id,
                    "storm_group_id": storm_group_id,
                    "positive": pos,
                    "pseudo_negative": neg,
                    "flood_geometry_repaired": event_geometry_repaired[key],
                }
            )
            log(f"[progress] {ymd} {tm[:2]}시: 양성 {pos:5d}  음성 {neg:6d}")

    total_pos = sum(s["positive"] for s in per_event_stats)
    total_neg = sum(s.get("pseudo_negative", s.get("negative", 0)) for s in per_event_stats)
    log("")
    log(f"[check] wrote {OUT_CSV.relative_to(ROOT)}")
    log(f"[check] rows {written:,}  |  positive {total_pos:,} ({total_pos/max(written,1)*100:.2f}%)")
    usable_events = [s for s in per_event_stats if s["positive"] > 0]
    log(f"[check] events with at least one positive: {len(usable_events)} / {len(events)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "target": "surface_flood_polygon_proxy (건물 점의 침수흔적도 포함 여부)",
                "row_unit": "one building x one flood event",
                "rows": written,
                "positive": total_pos,
                "negative": total_neg,
                "negative_label_source": "pseudo_negative_1km",
                "negative_label_quality": "pseudo_negative_1km",
                "positive_rate": round(total_pos / max(written, 1), 4),
                "events_total": len(events),
                "events_with_positive": len(usable_events),
                "negative_radius_m": NEGATIVE_RADIUS_M,
                "max_station_distance_km": MAX_STATION_DISTANCE_KM,
                "geometry_validation": geometry_stats,
                "per_event": per_event_stats,
                "inputs": {
                    "flood": str(FLOOD_GEOJSON.relative_to(ROOT)),
                    "buildings": str(BUILDINGS_GZ.relative_to(ROOT)),
                    "rain": str(EVENT_RAIN_CSV.relative_to(ROOT)),
                    "stations": str(STATION_CSV.relative_to(ROOT)),
                },
                "critical_limitations": [
                    "Target is inclusion of a building point in a surveyed SURFACE-flood "
                    "polygon, not underground car park flooding.",
                    "Negatives are only buildings within "
                    f"{NEGATIVE_RADIUS_M:.0f} m of a surveyed polygon of the SAME event. "
                    "They are weak pseudo-negatives, not verified non-flood observations; "
                    "buildings further away are dropped as unknown, not labelled 0.",
                    "Invalid source polygons are repaired with shapely.make_valid before "
                    "union, buffer, containment, and distance operations; repair counts are "
                    "recorded in geometry_validation.",
                    "Overture buildings carry no construction year, so a building built after "
                    "an event can still appear in that event's rows.",
                    "Elevation is a Copernicus GLO-30 DSM (surface, not bare earth), so tall "
                    "buildings and tree canopy bias it upward.",
                    "Rainfall is the nearest reporting station's value, not rainfall measured "
                    "at the building; rain_station_distance_km records how far that was.",
                    "The flood survey stops in 2021 and the agency no longer updates it.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log(f"[check] wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
