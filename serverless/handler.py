#!/usr/bin/env python3
"""Lambda handler: look up precomputed terrain risk, add live rainfall.

The model does not run here.  Its answers were baked into a 100 m grid
offline, because assembling its inputs needs 768 MB of DSM and a 1.5 GB
river index -- fine as a monthly batch, impossible per request.  What is
left at runtime is an array index, one upstream call, and a rule.

The function exists for one reason that a static site cannot cover: the KMA
API key must not reach the browser.  Everything else here could in principle
be client-side.

The function has no third-party dependencies at all.  The one projection it
needs lives in ``projection.py`` instead of pyproj, and the grid is read by
``npzreader.py`` instead of numpy -- a lookup wants an offset and a few
bytes, not an array library.  That matters practically: AWS publishes its
numpy-bearing layers only up to Python 3.11, so a 3.12 function would have
to pin a layer ARN and re-pin it whenever that version retires.  A
stdlib-only package has no layer to go stale.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from npzreader import load_npz
from projection import wgs84_to_grid

BUNDLE = Path(os.environ.get("BUNDLE_DIR", Path(__file__).parent / "bundle"))
KMA_KEY = os.environ.get("KMA_APIHUB_AUTH_KEY", "")
KMA_URL = "https://apihub.kma.go.kr/api/typ01/url/awsh.php"
RAIN_CACHE_SECONDS = 600

# Nodata sentinels for the integer-encoded grid bands.
NODATA_INT16 = -32768
NODATA_UINT16 = 65535

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
    grid = load_npz(BUNDLE / "risk_grid.npz")
    meta = json.loads((BUNDLE / "grid_meta.json").read_text(encoding="utf-8"))
    _STATE.update(
        {
            # Bands are stored as integers; see grid_meta.json "encoding".
            # 0 (score) and int16 min (elevations) mark nodata, which is why
            # a missing cell can never be mistaken for a real low value.
            "risk": grid["risk_score_u8"],
            "rel": grid["rel_elev_500m_dm"],
            "above": grid["elev_above_national_river_dm"],
            "dist": grid["dist_flood_m"],
            "meta": meta["grid"],
            "bands": json.loads((BUNDLE / "risk_bands.json").read_text(encoding="utf-8"))["bands"],
            "parking": json.loads((BUNDLE / "parking.json").read_text(encoding="utf-8")),
            "stations": json.loads((BUNDLE / "stations.json").read_text(encoding="utf-8")),
        }
    )
    return _STATE


def cell_of(lon: float, lat: float) -> tuple[int, int] | None:
    st = state()
    meta = st["meta"]
    x, y = wgs84_to_grid(lon, lat)
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
    raw = st["risk"].at(row, col)
    if raw == 0:
        return unknown
    score = (raw - 1) / 254.0

    band = band_of(score)
    evidence: dict[str, Any] = {}
    rel = st["rel"].at(row, col)
    if rel != NODATA_INT16:
        evidence["relativeElevationM"] = round(rel / 10.0, 1)
    above = st["above"].at(row, col)
    if above != NODATA_INT16:
        evidence["elevationAboveNationalRiverM"] = round(above / 10.0, 1)
    distance = st["dist"].at(row, col)
    if distance != NODATA_UINT16:
        evidence["distanceToFloodTraceM"] = distance

    return {
        "surveyStatus": "SURVEYED",
        "riskLevel": band["level"],
        "riskScore": round(score, 4),
        "rainTrigger": band["rain_trigger"],
        "evidence": evidence,
    }


def kma_hour_stamp(offset_hours: int = 0) -> str:
    """KST timestamp on the hour, which is the only form awsh accepts.

    The endpoint serves hourly observations, so a stamp with non-zero minutes
    returns a well-formed response containing nothing but column headers --
    HTTP 200 with zero rows, which reads as "no rain" unless the caller
    notices the row count.
    """
    moment = time.gmtime(time.time() + 9 * 3600 - offset_hours * 3600)
    return time.strftime("%Y%m%d%H", moment) + "00"


def fetch_hour(stamp: str) -> dict[str, float]:
    """One hour of nationwide readings, keyed by station id.

    A single call returns every station, so caching by timestamp means a
    burst of requests from one region costs one upstream call, not one each.
    """
    cached = _RAIN_CACHE.get(stamp)
    if cached and time.time() - cached[0] < RAIN_CACHE_SECONDS:
        return cached[1]

    # authKey is interpolated rather than urlencoded: the gateway rejects a
    # percent-encoded key.
    url = (
        f"{KMA_URL}?var=RN&tm={stamp}&stn=0&disp=1&help=0&authKey={KMA_KEY}"
    )
    with urllib.request.urlopen(url, timeout=6) as response:
        body = response.read().decode("cp949", "ignore")

    readings: dict[str, float] = {}
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # [0] stamp [1] station id [6] RN_HR1 in mm
        if len(parts) < 7:
            continue
        try:
            value = float(parts[6])
        except ValueError:
            continue
        # Negative values are KMA's missing-data markers, not dry readings.
        if value < 0:
            continue
        readings[parts[1]] = value
    _RAIN_CACHE[stamp] = (time.time(), readings)
    return readings


def nearest_station(lon: float, lat: float, available: set[str]) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for station_id, (station_lat, station_lon) in state()["stations"].items():
        if station_id not in available:
            continue
        km = math.hypot((station_lon - lon) * 88.0, (station_lat - lat) * 111.0)
        if best is None or km < best[1]:
            best = (station_id, km)
    return best


def rainfall_near(lon: float, lat: float) -> dict[str, Any]:
    """Rain at the nearest gauge over 1, 3 and 12 hours.

    Accumulations are summed from hourly readings rather than left null,
    because the KMA thresholds this service acts on are defined over 3 and 12
    hour windows -- without them only the 1-hour extreme-rain rule can ever
    fire.
    """
    if not KMA_KEY:
        return {"available": False, "reason": "NO_API_KEY"}

    # Twelve sequential round trips cost about eight seconds, which is most
    # of the timeout for data that is twelve independent fetches. Threads
    # bring it under a second; the work is entirely network wait.
    stamps = [kma_hour_stamp(offset) for offset in range(1, 13)]
    fetched: dict[str, dict[str, float]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_hour, stamp): stamp for stamp in stamps}
        for future in as_completed(futures):
            try:
                fetched[futures[future]] = future.result()
            except Exception as exc:  # noqa: BLE001 - one bad hour is not fatal
                # Record the class only. Upstream error text can echo the
                # request URL, which carries the API key.
                errors.append(type(exc).__name__)
                continue
    if not fetched:
        return {
            "available": False,
            "reason": "FETCH_FAILED",
            "errorKinds": sorted(set(errors)),
            "keyLength": len(KMA_KEY),
        }

    # Keep chronological order so hours[:3] really is the last three hours.
    hours = [fetched.get(stamp, {}) for stamp in stamps]
    latest = hours[0]
    if not latest:
        return {"available": False, "reason": "NO_DATA"}

    found = nearest_station(lon, lat, set(latest))
    if found is None:
        return {"available": False, "reason": "NO_STATION"}
    station_id, distance_km = found

    def total(count: int) -> float:
        return round(sum(h.get(station_id, 0.0) for h in hours[:count]), 1)

    result = {
        "available": True,
        "observedHourKst": kma_hour_stamp(1),
        "stationId": station_id,
        "stationDistanceKm": round(distance_km, 1),
        "mm1h": total(1),
        "mm3h": total(3),
        "mm12h": total(12),
        "hoursCollected": len(hours),
    }
    result["warningLevel"] = warning_level(result)
    return result


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

    # An unreachable weather API is not a dry sky. Reporting "비는 오지 않습니다"
    # because the fetch failed would state the one thing that gets someone
    # hurt -- the same error this function refuses to make for unsurveyed
    # terrain. The terrain half still stands, so it is reported alongside.
    if not rain.get("available"):
        return {
            "level": "UNKNOWN",
            "headline": f"강수 정보를 가져오지 못했습니다 (상시 위험도 {terrain['riskLevel']})",
            "reasons": reasons
            + ["비가 오지 않는다는 뜻이 아니라 기상청 조회에 실패했다는 뜻입니다"],
        }

    observed = rain.get("warningLevel", "없음")
    if observed != "없음":
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
