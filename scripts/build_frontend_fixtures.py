#!/usr/bin/env python3
"""Generate one sample response per UI state, using the real handler code.

The frontend has to render five alert levels, but which one comes back depends
on the weather. It is not raining anywhere today, so every live call returns
CALM and the screens that actually matter -- the ones telling someone to move
their car -- cannot be reached at all.

Hand-writing the samples would mean the UI is built against strings a person
guessed rather than strings the server sends. So the terrain half of every
fixture is a genuine grid lookup, and the alert half is produced by importing
``build_alert`` from the handler; only the rainfall numbers are supplied, at
the official thresholds in ``RAIN_LEVELS``. If the wording or the alert logic
changes, re-running this picks the change up instead of drifting.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BUNDLE_DIR", str(ROOT / "data/processed/serving-bundle"))
sys.path.insert(0, str(ROOT / "serverless"))

import handler  # noqa: E402

OUT = ROOT / "frontend/src/fixtures/floodRisk.fixtures.json"

# Points chosen for the terrain state they produce, verified against the grid.
POINTS = {
    "pohang": (36.03, 129.36),      # HIGH,      trigger 호우주의보
    "seoulGwanak": (37.48, 126.95),  # MODERATE,  trigger 호우경보
    "jeju": (33.51, 126.52),         # LOW,       trigger 극한호우
    "unsurveyed": (37.80, 128.50),   # UNKNOWN
}

DRY = {"available": True, "stationId": "138", "stationDistanceKm": 1.8,
       "mm1h": 0.0, "mm3h": 0.0, "mm12h": 0.0, "hoursCollected": 12,
       "observedHourKst": "202608230200", "warningLevel": "NONE"}

# Rain at each official threshold. Values sit just over the line in RAIN_LEVELS
# so the level each one produces is checked rather than asserted.
RAIN = {
    "HEAVY_RAIN_ADVISORY": {"mm1h": 22.0, "mm3h": 62.0, "mm12h": 88.0},
    "HEAVY_RAIN_WARNING": {"mm1h": 34.0, "mm3h": 92.0, "mm12h": 140.0},
    "EXTREME_RAIN": {"mm1h": 74.0, "mm3h": 118.0, "mm12h": 165.0},
}


def rain_payload(name: str) -> dict:
    body = {**DRY, **RAIN[name]}
    measured = handler.warning_level(body)
    if measured != name:
        raise SystemExit(f"{name} fixture measured as {measured}. Fix the RAIN values.")
    body["warningLevel"] = measured
    return body


def response(lat: float, lon: float, rain: dict) -> dict:
    terrain = handler.terrain_at(lon, lat)
    return {
        "location": {"lat": lat, "lon": lon},
        "terrain": terrain,
        "rainfall": rain,
        "alert": handler.build_alert(terrain, rain),
        "nearbyUndergroundParking": handler.nearby_parking(lon, lat, 2000.0, 3),
        "dataQuality": handler.DATA_QUALITY,
    }


def main() -> None:
    pohang, gwanak, jeju, unknown = (POINTS[k] for k in
                                     ("pohang", "seoulGwanak", "jeju", "unsurveyed"))

    fixtures = {
        # Terrain HIGH fires at the advisory level, so each step up the rain
        # scale moves the alert one step: WATCH -> PREPARE -> EVACUATE.
        "evacuate": response(*pohang, rain_payload("EXTREME_RAIN")),
        "prepare": response(*pohang, rain_payload("HEAVY_RAIN_WARNING")),
        "watch": response(*pohang, rain_payload("HEAVY_RAIN_ADVISORY")),
        "calm": response(*pohang, DRY),
        # Same rain, gentler terrain: a warning only reaches WATCH here. Useful
        # for checking the UI keys off `alert.level`, not off the rain level.
        "moderateTerrainHeavyRain": response(*gwanak, rain_payload("HEAVY_RAIN_WARNING")),
        "lowTerrainHeavyRain": response(*jeju, rain_payload("HEAVY_RAIN_WARNING")),
        # Must never render as safe.
        "unknown": response(*unknown, DRY),
        # KMA unreachable. Terrain still answers; the rain half degrades alone.
        "rainfallUnavailable": response(
            *pohang, {"available": False, "reason": "FETCH_FAILED"}
        ),
        "errorBadRequest": {"error": "Both lat and lon are required", "code": "BAD_REQUEST"},
        "errorOutOfRange": {
            "error": "The coordinates are outside South Korea",
            "code": "OUT_OF_RANGE",
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[결과] {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.1f} KB)")
    for name, body in fixtures.items():
        if "alert" not in body:
            print(f"  {name:<26} {body['code']}")
            continue
        print(f"  {name:<26} {body['alert']['level']:<9} "
              f"지형 {body['terrain']['riskLevel']:<9} "
              f"강수 {body['rainfall'].get('warningLevel', '-')}")


if __name__ == "__main__":
    main()
