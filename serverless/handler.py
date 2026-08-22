#!/usr/bin/env python3
"""Lambda handler: look up precomputed terrain risk, add live rainfall.

The model does not run here.  Its answers were baked into a 100 m grid
offline, because assembling its inputs needs 768 MB of DSM and a 1.5 GB
river index -- fine as a monthly batch, impossible per request.  What is
left at runtime is an array index, one upstream call, and a rule.

The function exists for one reason that a static site cannot cover: the KMA
API key must not reach the browser.  Everything else here could in principle
be client-side.

Two invariants matter more than anything else in this file.

Outside the surveyed area every band is nodata, and the response says
UNKNOWN.  It must never say safe.  Incheon holds 69,142 basement buildings
and one flood overlap, not because it is dry but because 144 polygons were
ever surveyed there.

``riskScore`` is a ranking score, never a probability.  It was validated by
PR-AUC, which measures ordering, and was never calibrated against observed
frequencies.  No field in the response is named "probability", and the
disclaimer travels with the payload so a client cannot lose it.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer

BUNDLE = Path(os.environ.get("BUNDLE_DIR", Path(__file__).parent / "bundle"))
KMA_KEY = os.environ.get("KMA_APIHUB_AUTH_KEY", "")
KMA_URL = "https://apihub.kma.go.kr/api/typ01/url/awsh.php"
RAIN_CACHE_SECONDS = 600

# Official KMA 호우특보 criteria, ordered most severe first.  These are not
# fitted: the 06 analysis measured a non-monotonic flood rate against
# rainfall and concluded the event count cannot support learning them.
RAIN_LEVELS = [
    ("극한호우", lambda r: (r["mm1h"] >= 72) or (r["mm1h"] >= 50 and r["mm3h"] >= 90)),
    ("호우경보", lambda r: r["mm3h"] >= 90 or r["mm12h"] >= 180),
    ("호우주의보", lambda r: r["mm3h"] >= 60 or r["mm12h"] >= 110),
]
RAIN_SEVERITY = {"없음": 0, "호우주의보": 1, "호우경보": 2, "극한호우": 3}

ALERT_BY_GAP = {
    2: ("EVACUATE", "지금 차를 빼세요"),
    1: ("PREPARE", "차량 이동을 준비하세요"),
    0: ("WATCH", "상황을 지켜보세요"),
}

_STATE: dict[str, Any] = {}
_RAIN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def state() -> dict[str, Any]:
    """Load the bundle once per container, not once per request."""
    if _STATE:
        return _STATE
    grid = np.load(BUNDLE / "risk_grid.npz")
    meta = json.loads((BUNDLE / "grid_meta.json").read_text(encoding="utf-8"))
    _STATE.update(
        {
            "risk": grid["risk_score"],
            "rel": grid["rel_elev_500m"],
            "above": grid["elev_above_national_river"],
            "dist": grid["dist_flood_m"],
            "meta": meta["grid"],
            "bands": json.loads((BUNDLE / "risk_bands.json").read_text(encoding="utf-8"))["bands"],
            "parking": json.loads((BUNDLE / "parking.json").read_text(encoding="utf-8")),
            "to_grid": Transformer.from_crs(
                "EPSG:4326", f"EPSG:{meta['grid']['epsg']}", always_xy=True
            ),
        }
    )
    return _STATE


def cell_of(lon: float, lat: float) -> tuple[int, int] | None:
    st = state()
    meta = st["meta"]
    x, y = st["to_grid"].transform(lon, lat)
    col = int((x - meta["origin_x"]) // meta["cell_m"])
    row = int((meta["origin_y_top"] - y) // meta["cell_m"])
    if 0 <= row < meta["rows"] and 0 <= col < meta["cols"]:
        return row, col
    return None


def band_of(score: float) -> dict[str, Any]:
    for band in state()["bands"]:
        if score >= band["min_score"]:
            return band
    return state()["bands"][-1]


def terrain_at(lon: float, lat: float) -> dict[str, Any]:
    st = state()
    cell = cell_of(lon, lat)
    unknown = {
        "surveyStatus": "NOT_SURVEYED",
        "riskLevel": "UNKNOWN",
        "riskScore": None,
        "rainTrigger": "호우경보",
        "evidence": {},
        "note": "이 지역은 침수 조사 기록이 없습니다. 안전하다는 뜻이 아닙니다.",
    }
    if cell is None:
        return unknown
    row, col = cell
    score = float(st["risk"][row, col])
    if not math.isfinite(score):
        return unknown

    band = band_of(score)
    evidence: dict[str, Any] = {}
    rel = float(st["rel"][row, col])
    if math.isfinite(rel):
        evidence["relativeElevationM"] = round(rel, 1)
    above = float(st["above"][row, col])
    if math.isfinite(above):
        evidence["elevationAboveNationalRiverM"] = round(above, 1)
    distance = int(st["dist"][row, col])
    if distance != 65535:
        evidence["distanceToFloodTraceM"] = distance

    return {
        "surveyStatus": "SURVEYED",
        "riskLevel": band["level"],
        "riskScore": round(score, 4),
        "rainTrigger": band["rain_trigger"],
        "evidence": evidence,
    }


def rainfall_near(lon: float, lat: float) -> dict[str, Any]:
    """Current rainfall from KMA, cached because it is a per-station value."""
    if not KMA_KEY:
        return {"available": False, "reason": "NO_API_KEY"}

    stamp = time.strftime("%Y%m%d%H%M", time.gmtime(time.time() + 9 * 3600))[:11] + "0"
    key = f"{stamp}:{round(lon, 2)}:{round(lat, 2)}"
    cached = _RAIN_CACHE.get(key)
    if cached and time.time() - cached[0] < RAIN_CACHE_SECONDS:
        return cached[1]

    query = urllib.parse.urlencode(
        {"tm": stamp, "disp": "0", "help": "0", "authKey": KMA_KEY}
    )
    try:
        with urllib.request.urlopen(f"{KMA_URL}?{query}", timeout=5) as response:
            body = response.read().decode("euc-kr", "ignore")
    except Exception as exc:  # noqa: BLE001 - degraded, not fatal
        return {"available": False, "reason": type(exc).__name__}

    result = parse_kma(body, lon, lat)
    _RAIN_CACHE[key] = (time.time(), result)
    return result


def parse_kma(body: str, lon: float, lat: float) -> dict[str, Any]:
    """Pick the nearest reporting station from the AWS hourly response."""
    best: dict[str, Any] | None = None
    for line in body.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            station_lon = float(parts[2])
            station_lat = float(parts[1])
            mm1h = float(parts[4])
        except ValueError:
            continue
        if mm1h < 0:
            continue
        km = math.hypot((station_lon - lon) * 88.0, (station_lat - lat) * 111.0)
        if best is None or km < best["stationDistanceKm"]:
            best = {
                "available": True,
                "stationId": parts[0],
                "stationDistanceKm": round(km, 1),
                "mm1h": mm1h,
                # The hourly endpoint reports one hour; longer windows need the
                # accumulation endpoint and are reported as unavailable rather
                # than guessed at.
                "mm3h": None,
                "mm12h": None,
            }
    if best is None:
        return {"available": False, "reason": "NO_STATION"}
    best["warningLevel"] = warning_level(best)
    return best


def warning_level(rain: dict[str, Any]) -> str:
    usable = {k: (rain.get(k) or 0.0) for k in ("mm1h", "mm3h", "mm12h")}
    for name, test in RAIN_LEVELS:
        if test(usable):
            return name
    return "없음"


def build_alert(terrain: dict[str, Any], rain: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    evidence = terrain.get("evidence", {})
    if "relativeElevationM" in evidence:
        reasons.append(f"이 위치는 주변보다 {evidence['relativeElevationM']}m 낮습니다")
    if "elevationAboveNationalRiverM" in evidence:
        reasons.append(
            f"가장 가까운 국가하천 수면보다 {evidence['elevationAboveNationalRiverM']}m 높습니다"
        )
    if "distanceToFloodTraceM" in evidence:
        reasons.append(f"과거 침수 구역까지 {evidence['distanceToFloodTraceM']}m입니다")

    if terrain["riskLevel"] == "UNKNOWN":
        return {
            "level": "UNKNOWN",
            "headline": "이 지역은 침수 조사 기록이 없습니다",
            "reasons": reasons + ["안전하다는 뜻이 아니라 확인된 자료가 없다는 뜻입니다"],
        }

    observed = rain.get("warningLevel", "없음") if rain.get("available") else "없음"
    if rain.get("available") and observed != "없음":
        reasons.append(f"현재 강수는 {observed} 기준을 넘었습니다")

    gap = RAIN_SEVERITY[observed] - RAIN_SEVERITY[terrain["rainTrigger"]]
    if observed == "없음":
        return {
            "level": "CALM",
            "headline": f"현재 비는 오지 않습니다 (상시 위험도 {terrain['riskLevel']})",
            "reasons": reasons,
        }
    level, headline = ALERT_BY_GAP.get(max(min(gap, 2), 0), ALERT_BY_GAP[0])
    return {"level": level, "headline": headline, "reasons": reasons}


def nearby_parking(lon: float, lat: float, radius_m: float, limit: int) -> list[dict[str, Any]]:
    out = []
    for item in state()["parking"]:
        km = math.hypot((item["lon"] - lon) * 88.0, (item["lat"] - lat) * 111.0)
        metres = km * 1000.0
        if metres <= radius_m:
            out.append({**item, "distanceM": int(metres)})
    out.sort(key=lambda p: p["distanceM"])
    return out[:limit]


def respond(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "public, max-age=60",
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    try:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            import base64

            body = base64.b64decode(body).decode("utf-8")
        request = json.loads(body) if isinstance(body, str) else body
        lon = float(request["lon"])
        lat = float(request["lat"])
    except (KeyError, TypeError, ValueError):
        return respond(400, {"error": "lat과 lon이 필요합니다", "code": "BAD_REQUEST"})

    if not (124.0 <= lon <= 132.0 and 33.0 <= lat <= 39.0):
        return respond(
            422, {"error": "대한민국 범위 밖 좌표입니다", "code": "OUT_OF_RANGE"}
        )

    options = request.get("nearbyParking") or {}
    terrain = terrain_at(lon, lat)
    rain = rainfall_near(lon, lat)

    return respond(
        200,
        {
            "location": {"lat": lat, "lon": lon},
            "terrain": terrain,
            "rainfall": rain,
            "alert": build_alert(terrain, rain),
            "nearbyUndergroundParking": nearby_parking(
                lon,
                lat,
                float(options.get("radiusM", 1000)),
                int(options.get("limit", 5)),
            )
            if options.get("include", True)
            else [],
            "dataQuality": {
                "labelMeaning": "SURFACE_FLOOD_TRACE",
                "floodSurveyPeriod": "2002-2022",
                "disclaimer": (
                    "지하주차장 침수 예측이 아니라, 과거 지표면 침수 기록에서 "
                    "측정한 지형 위험도입니다. riskScore는 순위 점수이며 확률이 아닙니다."
                ),
            },
        },
    )
