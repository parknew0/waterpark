#!/usr/bin/env python3
"""Build the surface-flood training table for Waterpark.

Why this exists
---------------
The original target -- "will this underground car park flood" -- cannot be
trained. Only 9 buildings with confirmed underground parking sit inside a flood
polygon, because 침수흔적도 mostly surveyed farmland and river plains while
underground parking is urban. See docs/research-log.md.

So this builds the achievable target instead: **did the ground surface at this
building flood during this rainfall event**. That is a real, officially surveyed
fact, and the trained model becomes one input to the underground-parking risk
score rather than the whole answer.

The negative-label rule
-----------------------
A building outside a flood polygon is NOT automatically "did not flood" -- it may
simply never have been surveyed. docs/02 section 3.3 forbids that shortcut. So a
building only becomes a negative when it sits within NEGATIVE_RADIUS_M of a
polygon that WAS surveyed in that same event. Everything further away is dropped
as unknown rather than labelled 0.

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
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
FLOOD_GEOJSON = ROOT / "data/raw/flood-trace/gyeongbuk_flood_2002_2022.geojson"
BUILDINGS_GZ = ROOT / "data/processed/gyeongbuk_buildings_elevation.csv.gz"
EVENT_RAIN_CSV = ROOT / "data/processed/gyeongbuk_flood_event_rain.csv"
STATION_CSV = ROOT / "data/raw/kma-stations/kma_station_list.csv"

OUT_CSV = ROOT / "data/processed/gyeongbuk_flood_training_table.csv"
OUT_DIR = ROOT / "outputs/gyeongbuk-flood-model"
MANIFEST = OUT_DIR / "training_table_manifest.json"

# A building this close to a surveyed flood polygon is treated as having been
# inside the surveyed neighbourhood, so "not flooded" is a real observation.
NEGATIVE_RADIUS_M = 1000.0
DEG = 1.0 / 111000.0  # rough metres -> degrees, fine at this latitude
MAX_STATION_DISTANCE_KM = 30.0


def log(msg: str) -> None:
    print(msg, flush=True)


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
            key = (r["fldn_bgng_ymd"], r["fldn_bgng_tm"])
            rain[key][r["station_id"]] = {
                "rain_1h": r["rain_1h"],
                "rain_3h": r["rain_3h"],
                "rain_6h": r["rain_6h"],
                "rain_12h": r["rain_12h"],
                "rain_24h": r["rain_24h"],
                "hours": r["hours_available_of_24"],
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
    for f in feats:
        p = f["properties"]
        key = (p["fldn_bgng_ymd"], p["fldn_bgng_tm"])
        events[key].append(shape(f["geometry"]))
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
        "rain_station_id",
        "rain_station_distance_km",
        "flood",
    ]

    per_event_stats = []
    written = 0
    no_rain = 0

    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)

        for key in sorted(events):
            ymd, tm = key
            polys = events[key]
            union = unary_union(polys)
            buffered = union.buffer(NEGATIVE_RADIUS_M * DEG)
            p_union = prep(union)
            p_buffer = prep(buffered)

            # Candidate buildings: bbox query, then a real containment test.
            candidates = [i for i in tree.query(buffered) if p_buffer.contains(points[i])]
            if not candidates:
                per_event_stats.append({"event": f"{ymd}-{tm}", "positive": 0, "negative": 0})
                continue

            # Rain: pick the nearest station that actually reported this event.
            rain_for_event = event_rain.get(key, {})
            active = stations_active_on(stations, ymd)
            usable = [
                (sid, lonlat)
                for sid, lonlat in active.items()
                if sid in rain_for_event and rain_for_event[sid]["rain_24h"] != ""
            ]
            if not usable:
                no_rain += 1
                log(f"[warn] {ymd} {tm}: no station with rainfall; event skipped")
                per_event_stats.append({"event": f"{ymd}-{tm}", "positive": 0, "negative": 0})
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

                writer.writerow(
                    [
                        b["building_id"],
                        f"GB-{ymd}-{tm}",
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
                        st_ids[j],
                        round(float(d[j]), 2),
                        1 if inside else 0,
                    ]
                )
                written += 1
                pos += inside
                neg += not inside

            per_event_stats.append({"event": f"{ymd}-{tm}", "positive": pos, "negative": neg})
            log(f"[progress] {ymd} {tm[:2]}시: 양성 {pos:5d}  음성 {neg:6d}")

    total_pos = sum(s["positive"] for s in per_event_stats)
    total_neg = sum(s["negative"] for s in per_event_stats)
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
                "target": "surface_flood_observed (건물 위치의 지표면 침수 여부)",
                "row_unit": "one building x one flood event",
                "rows": written,
                "positive": total_pos,
                "negative": total_neg,
                "positive_rate": round(total_pos / max(written, 1), 4),
                "events_total": len(events),
                "events_with_positive": len(usable_events),
                "negative_radius_m": NEGATIVE_RADIUS_M,
                "max_station_distance_km": MAX_STATION_DISTANCE_KM,
                "per_event": per_event_stats,
                "inputs": {
                    "flood": str(FLOOD_GEOJSON.relative_to(ROOT)),
                    "buildings": str(BUILDINGS_GZ.relative_to(ROOT)),
                    "rain": str(EVENT_RAIN_CSV.relative_to(ROOT)),
                    "stations": str(STATION_CSV.relative_to(ROOT)),
                },
                "critical_limitations": [
                    "Target is SURFACE flooding at the building location, not underground "
                    "car park flooding. They are not the same event.",
                    "Negatives are only buildings within "
                    f"{NEGATIVE_RADIUS_M:.0f} m of a surveyed polygon of the SAME event. "
                    "Buildings further away are dropped as unknown, not labelled 0.",
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
