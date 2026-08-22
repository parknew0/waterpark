#!/usr/bin/env python3
"""Build the isolated 2022 Typhoon Hinnamnor historical replay dataset.

Confirmed observations and public building attributes are kept separate from
the illustrative map radius used by the frontend. The radius is not an
observed inundation boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import osmnx as ox
import pandas as pd

from data_paths import PROCESSED_ML_PREDICTIONS, RAW_OSM_CACHE, ROOT


BUILDING_SOURCE = PROCESSED_ML_PREDICTIONS / "gyeongbuk_underground_parking_risk.csv"
DEFAULT_OUTPUT = ROOT / "frontend" / "public" / "data" / "hinnamnor-2022-replay.json"
BUILDING_NAME = "우방신세계타운(1차)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def na_to_none(value):
    return None if pd.isna(value) else value


def load_focus_building() -> dict:
    buildings = pd.read_csv(BUILDING_SOURCE, low_memory=False)
    matches = buildings[
        (buildings["building_name"] == BUILDING_NAME)
        & buildings["legal_dong_name"].astype(str).str.contains("포항시 남구 인덕동", na=False)
    ]
    if matches.empty:
        raise RuntimeError("Focus apartment complex was not found")
    return {
        "building_ids": matches["building_id"].astype(str).tolist(),
        "name": BUILDING_NAME,
        "location_label": "Indeok-dong, Nam-gu, Pohang-si",
        "latitude": round(float(matches["latitude"].mean()), 7),
        "longitude": round(float(matches["longitude"].mean()), 7),
        "underground_parking_status": "CONFIRMED_BASEMENT_PARKING_USE",
        "underground_parking_confirmed": bool(matches["underground_parking_confirmed"].all()),
        "underground_floor_count": int(matches["underground_floor_count_gis"].max()),
        "surface_elevation_m_min": round(float(matches["surface_elevation_m"].min()), 2),
        "surface_elevation_m_mean": round(float(matches["surface_elevation_m"].mean()), 2),
        "static_risk": "NOT_USED_FOR_HISTORICAL_REPLAY",
        "historical_flood_overlap_in_current_layer": bool(matches["inside_past_flood_area"].any()),
    }


def load_naengcheon(center: tuple[float, float]) -> list[list[float]]:
    ox.settings.use_cache = True
    ox.settings.cache_folder = RAW_OSM_CACHE
    waterways = ox.features.features_from_point(
        center,
        tags={"waterway": ["river", "stream"]},
        dist=3_500,
    )
    named = waterways[waterways.get("name").astype(str) == "냉천"]
    if named.empty:
        raise RuntimeError("OSM에서 냉천 선형을 찾지 못했습니다.")
    geometry = max(named.geometry, key=lambda item: item.length)
    if geometry.geom_type != "LineString":
        geometry = max(geometry.geoms, key=lambda item: item.length)
    return [[round(float(x), 7), round(float(y), 7)] for x, y in geometry.coords]


def main() -> None:
    args = parse_args()
    building = load_focus_building()
    river = load_naengcheon((building["latitude"], building["longitude"]))
    generated_at = datetime.now(timezone.utc).isoformat()

    result = {
        "schema_version": 1,
        "mode": "HISTORICAL_REPLAY",
        "event": {
            "id": "KR-GB-POHANG-HINNAMNOR-2022-09-06",
            "name": "Typhoon Hinnamnor — Pohang",
            "date_kst": "2022-09-06",
            "focus": building,
        },
        "rainfall": {
            "station": "Pohang observation station",
            "station_id": "138",
            "rolling_max_mm": [
                {"duration_minutes": 60, "rainfall_mm": 77.0},
                {"duration_minutes": 120, "rainfall_mm": 147.9},
                {"duration_minutes": 180, "rainfall_mm": 203.2},
                {"duration_minutes": 360, "rainfall_mm": 314.5},
                {"duration_minutes": 540, "rainfall_mm": 359.8},
                {"duration_minutes": 720, "rainfall_mm": 378.7},
            ],
            "calendar_day_mm": 342.4,
            "calendar_day_note": "KMA September 6 calendar-day total; rolling windows cross midnight.",
        },
        "river": {
            "name": "Naengcheon",
            "source": "OpenStreetMap current waterway geometry",
            "coordinates": river,
        },
        "timeline": [
            {
                "time_kst": "2022-09-05 21:00",
                "title": "Rain bands intensify",
                "detail": "The replay opens before the most destructive early-morning period.",
                "reconstruction_radius_m": 70,
                "rainfall_duration_minutes": 60,
            },
            {
                "time_kst": "2022-09-06 04:50",
                "title": "Hinnamnor makes landfall near Geoje",
                "detail": "KMA reports landfall at 04:50 KST before the storm crossed the southeast.",
                "reconstruction_radius_m": 150,
                "rainfall_duration_minutes": 180,
            },
            {
                "time_kst": "2022-09-06 06:30",
                "title": "Underground parking emergency",
                "detail": "Public reports place the vehicle-move announcement around 06:30 KST.",
                "reconstruction_radius_m": 260,
                "rainfall_duration_minutes": 360,
            },
            {
                "time_kst": "2022-09-06 07:41",
                "title": "Rescue reports begin",
                "detail": "Emergency calls were reported as flooding overwhelmed the site.",
                "reconstruction_radius_m": 390,
                "rainfall_duration_minutes": 540,
            },
        ],
        "incident": {
            "summary": "Seven people died and two survived in the Indeok-dong underground parking incident.",
            "tone": "memorial, not gamified",
        },
        "limitations": [
            "The expanding red area is an illustrative reconstruction radius, not an observed inundation polygon.",
            "The local Ministry of the Interior and Safety flood-trace copy contains Gyeongbuk records only through 2021, so it cannot validate the 2022 footprint.",
            "OSM river geometry is current, not a snapshot of the river geometry on 2022-09-06.",
            "The local static-risk score predates this event reconstruction and must not be presented as a successful Hinnamnor prediction.",
        ],
        "sources": [
            {
                "label": "KMA 2022 Typhoon Report",
                "url": "https://www.kma.go.kr/download_01/typhoon/typreport_2022.pdf",
                "role": "track and 04:50 landfall time",
            },
            {
                "label": "KMA September 2022 Climate Newsletter",
                "url": "https://www.weather.go.kr/download_02/ellinonewsletter_2022_09.pdf",
                "role": "Pohang calendar-day rainfall 342.4 mm",
            },
            {
                "label": "Naengcheon basin Hinnamnor hydrology study",
                "url": "https://journal.dssms.org/articles/xml/5aEx/",
                "role": "observed rolling rainfall and river-overflow context",
            },
            {
                "label": "ADRC Korea Country Report FY2024",
                "url": "https://web.adrc.asia/countryreport/KOR/2024/Korea_CountryReport_FY2024.pdf",
                "role": "incident location and casualty outcome",
            },
        ],
        "provenance": {
            "generated_at": generated_at,
            "building_source": str(BUILDING_SOURCE.relative_to(ROOT)),
            "building_source_sha256": sha256(BUILDING_SOURCE),
            "checked_at": "2026-08-23",
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.relative_to(ROOT)), "river_points": len(river)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
