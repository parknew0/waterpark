#!/usr/bin/env python3
"""Attach KMA hourly rainfall to Waterpark's Gyeongbuk flood-trace events.

Flood source: Esri Korea Living Atlas mirror of the official 행정안전부
침수흔적도 (2002-2022), approved via safetydata.go.kr dataSn=108.
    https://portal.esrikr.com/arcgis/rest/services/Hosted/Flood_2002_2022/FeatureServer

Rain source: KMA API Hub "AWS 시간통계 자료 조회" (awsh.php, var=RN), approved
application seqApi=2&seqApiSub=239.

This script groups flood records into (date, start time) events, derives a
conservative storm group, and attaches complete 1/3/6/12/24-hour rainfall
windows per station. It does not join buildings or polygons yet -- that needs
the building/GIS join described in docs/01 and docs/02.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from data_paths import (
    INTERIM_FLOOD_TRACE_GYEONGBUK,
    PROCESSED_RAINFALL,
    RAW_FLOOD_TRACE,
    RAW_KMA_RAIN,
    ROOT,
)

RAW_GEOJSON = RAW_FLOOD_TRACE / "gyeongbuk_flood_2002_2022.geojson"
RAW_RAIN_JSONL = RAW_KMA_RAIN / "gyeongbuk_flood_event_hourly_rain_raw.jsonl"
OUTPUT_DIR = ROOT / "outputs/gyeongbuk-flood"
ENV_FILE = ROOT / ".env"

RECORDS_CSV = INTERIM_FLOOD_TRACE_GYEONGBUK / "gyeongbuk_flood_records.csv"
EVENTS_CSV = INTERIM_FLOOD_TRACE_GYEONGBUK / "gyeongbuk_flood_events.csv"
EVENT_RAIN_CSV = PROCESSED_RAINFALL / "gyeongbuk_flood_event_rain.csv"
MANIFEST = OUTPUT_DIR / "manifest.json"
SAMPLE_CSV = OUTPUT_DIR / "gyeongbuk_flood_event_rain_sample.csv"

KMA_BASE = "https://apihub.kma.go.kr/api/typ01/url/awsh.php"
MISSING_BELOW = -90.0  # KMA uses -99 / -99.0 as the missing-value sentinel.
RAIN_WINDOWS = (1, 3, 6, 12, 24)


def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def load_flood_features() -> list[dict]:
    data = json.loads(RAW_GEOJSON.read_text(encoding="utf-8"))
    return data["features"]


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


def assign_storm_group_ids(event_rows: list[dict]) -> None:
    """Group timestamps on the same or consecutive calendar days conservatively.

    This deliberately over-groups rather than splitting one storm into several
    train/test groups. Unknown dates stay isolated so unrelated missing records
    are never merged into a shared storm.
    """
    parsed_dates: dict[str, datetime] = {}
    for row in event_rows:
        ymd = row["fldn_bgng_ymd"]
        try:
            parsed_dates[ymd] = datetime.strptime(ymd, "%Y%m%d")
        except (TypeError, ValueError):
            continue

    date_to_group: dict[str, str] = {}
    previous: datetime | None = None
    current_group = ""
    for ymd, day in sorted(parsed_dates.items(), key=lambda item: item[1]):
        if previous is None or (day.date() - previous.date()).days > 1:
            current_group = f"GB-STORM-{ymd}"
        date_to_group[ymd] = current_group
        previous = day

    for row in event_rows:
        ymd = row["fldn_bgng_ymd"]
        row["storm_group_id"] = date_to_group.get(
            ymd,
            f"GB-STORM-UNKNOWN-{hashlib.sha256(row['event_id'].encode()).hexdigest()[:12]}",
        )


def parse_kma_float(raw: str):
    try:
        v = float(raw)
    except ValueError:
        return None
    if v <= MISSING_BELOW:
        return None
    return v


def fetch_hourly_rain(tm: str, auth_key: str, retries: int = 4) -> dict:
    url = f"{KMA_BASE}?var=RN&tm={tm}&stn=0&disp=1&help=0&authKey={auth_key}"
    delay = 1.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                body = resp.read().decode("cp949", errors="ignore")
            stations = {}
            for line in body.splitlines():
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 8:
                    continue
                stn = parts[1]
                rn_day = parse_kma_float(parts[4])
                rn_hr1 = parse_kma_float(parts[6])
                stations[stn] = {"rn_hr1": rn_hr1, "rn_day": rn_day}
            return stations
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 15)
    return {}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    load_env()
    auth_key = os.environ.get("KMA_APIHUB_AUTH_KEY")
    if not auth_key:
        raise SystemExit("KMA_APIHUB_AUTH_KEY missing from .env")

    features = load_flood_features()
    print(f"[check] loaded {len(features)} flood polygon records from {RAW_GEOJSON.relative_to(ROOT)}")

    non_gb = [
        f for f in features if clean_text(f["properties"].get("stdg_ctpv_cd")) != "47"
    ]
    if non_gb:
        print(f"[warn] {len(non_gb)} records are outside stdg_ctpv_cd=47 (Gyeongbuk) -- check the source export")

    # 1) flat records table (geometry dropped -- no geopandas/shapely available here)
    RECORDS_CSV.parent.mkdir(parents=True, exist_ok=True)
    EVENT_RAIN_CSV.parent.mkdir(parents=True, exist_ok=True)
    prop_keys = sorted({k for f in features for k in f["properties"].keys()})
    fieldnames = ["objectid"] + [k for k in prop_keys if k != "objectid"]
    with RECORDS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for f in features:
            writer.writerow(f["properties"])
    print(f"[check] wrote {RECORDS_CSV.relative_to(ROOT)} ({len(features)} rows)")

    # 2) group into (date, start time) events
    events = defaultdict(list)
    for f in features:
        p = f["properties"]
        ymd = normalized_date(p.get("fldn_bgng_ymd"))
        tm = normalized_time(p.get("fldn_bgng_tm"))
        # Records with no date cannot safely be merged into one event. Preserve
        # each source record as its own unknown-time event for quality review.
        source_token = clean_text(p.get("objectid") or p.get("sn")) if not ymd else ""
        events[(ymd, tm, source_token)].append(p)

    event_rows = []
    for (ymd, tm, source_token), props_list in sorted(events.items(), key=lambda item: item[0]):
        disaster_names = sorted(
            {clean_text(p.get("fldn_dst_nm")) for p in props_list if clean_text(p.get("fldn_dst_nm"))}
        )
        sgg_codes = sorted(
            {clean_text(p.get("stdg_sgg_cd")) for p in props_list if clean_text(p.get("stdg_sgg_cd"))}
        )
        years = sorted(
            {clean_text(p.get("fldn_yr")) for p in props_list if clean_text(p.get("fldn_yr"))}
        )
        event_date_token = ymd or f"UNKNOWN-{source_token or 'NOID'}"
        event_time_token = tm or "UNKNOWN"
        event_rows.append(
            {
                "event_id": f"GB-{event_date_token}-{event_time_token}",
                "fldn_bgng_ymd": ymd,
                "fldn_bgng_tm": tm,
                "fldn_yr": years[0] if years else "",
                "polygon_count": len(props_list),
                "sgg_codes": ";".join(str(s) for s in sgg_codes),
                "disaster_names": " | ".join(disaster_names),
            }
        )
    assign_storm_group_ids(event_rows)

    with EVENTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "event_id",
                "storm_group_id",
                "fldn_bgng_ymd",
                "fldn_bgng_tm",
                "fldn_yr",
                "polygon_count",
                "sgg_codes",
                "disaster_names",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(event_rows)
    print(f"[check] wrote {EVENTS_CSV.relative_to(ROOT)} ({len(event_rows)} distinct date+time events)")
    storm_group_count = len({row["storm_group_id"] for row in event_rows})
    print(f"[check] conservatively grouped them into {storm_group_count} storm groups")

    # 3) figure out which hourly timestamps are needed: T, T-1h, ..., T-23h per event
    event_hours: dict[str, list[datetime]] = {}
    needed_ts: set[datetime] = set()
    bad_time = 0
    for row in event_rows:
        try:
            base = datetime.strptime(row["fldn_bgng_ymd"] + row["fldn_bgng_tm"], "%Y%m%d%H%M")
        except ValueError:
            event_hours[row["event_id"]] = []
            bad_time += 1
            continue
        hours = [base - timedelta(hours=h) for h in range(24)]
        event_hours[row["event_id"]] = hours
        needed_ts.update(hours)
    if bad_time:
        print(f"[warn] {bad_time} events had an unparseable fldn_bgng_ymd/fldn_bgng_tm")

    needed_ts_sorted = sorted(needed_ts)
    print(f"[check] {len(needed_ts_sorted)} distinct hourly timestamps needed for {len(event_rows)} events")

    # 4) fetch (cached, resumable via the raw JSONL)
    RAW_RAIN_JSONL.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, dict] = {}
    if RAW_RAIN_JSONL.exists():
        with RAW_RAIN_JSONL.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                cache[rec["tm"]] = rec["stations"]

    to_fetch = [ts for ts in needed_ts_sorted if ts.strftime("%Y%m%d%H%M") not in cache]
    print(f"[check] {len(cache)} timestamps already cached, {len(to_fetch)} to fetch now")

    with RAW_RAIN_JSONL.open("a", encoding="utf-8") as fh:
        for i, ts in enumerate(to_fetch, 1):
            tm_str = ts.strftime("%Y%m%d%H%M")
            stations = fetch_hourly_rain(tm_str, auth_key)
            fh.write(json.dumps({"tm": tm_str, "stations": stations}, ensure_ascii=False) + "\n")
            fh.flush()
            cache[tm_str] = stations
            if i % 25 == 0 or i == len(to_fetch):
                print(f"[progress] fetched {i}/{len(to_fetch)} hourly timestamps")
            time.sleep(0.2)

    # 5) compute complete rainfall windows per event per station
    all_stations = sorted({s for v in cache.values() for s in v.keys()})
    rows_written = 0
    rows_dropped_empty = 0
    with EVENT_RAIN_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(
            [
                "event_id",
                "storm_group_id",
                "fldn_bgng_ymd",
                "fldn_bgng_tm",
                "station_id",
                "rain_1h",
                # 3h and 12h exist so the official KMA 호우특보 thresholds can be
                # applied directly: 주의보 3h>=60 or 12h>=110, 경보 3h>=90 or 12h>=180.
                "rain_3h",
                "rain_6h",
                "rain_12h",
                "rain_24h",
                "hours_available_1h",
                "hours_available_3h",
                "hours_available_6h",
                "hours_available_12h",
                "hours_available_24h",
            ]
        )
        for row in event_rows:
            hours = event_hours[row["event_id"]]
            if not hours:
                continue
            hour_keys = [h.strftime("%Y%m%d%H%M") for h in hours]
            for stn in all_stations:
                vals = [cache.get(hk, {}).get(stn, {}).get("rn_hr1") for hk in hour_keys]
                available = [v for v in vals if v is not None]
                if not available:
                    rows_dropped_empty += 1
                    continue
                def window_value(hours_back: int) -> tuple[float | None, int]:
                    chunk = vals[:hours_back]
                    present = [v for v in chunk if v is not None]
                    # A partial sum is not an N-hour rainfall total. Keep the
                    # observed-hour count, but leave rainfall null unless the
                    # entire requested window is present.
                    value = round(sum(present), 1) if len(present) == hours_back else None
                    return value, len(present)

                window_values = {window: window_value(window) for window in RAIN_WINDOWS}
                writer.writerow(
                    [
                        row["event_id"],
                        row["storm_group_id"],
                        row["fldn_bgng_ymd"],
                        row["fldn_bgng_tm"],
                        stn,
                        window_values[1][0],
                        window_values[3][0],
                        window_values[6][0],
                        window_values[12][0],
                        window_values[24][0],
                        window_values[1][1],
                        window_values[3][1],
                        window_values[6][1],
                        window_values[12][1],
                        window_values[24][1],
                    ]
                )
                rows_written += 1
    print(
        f"[check] wrote {EVENT_RAIN_CSV.relative_to(ROOT)} ({rows_written} event x station rows, "
        f"{rows_dropped_empty} all-missing rows dropped)"
    )

    # 6) sample + manifest
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with EVENT_RAIN_CSV.open(encoding="utf-8") as src, SAMPLE_CSV.open("w", newline="", encoding="utf-8") as dst:
        for i, line in enumerate(src):
            if i > 200:
                break
            dst.write(line)

    manifest = {
        "created_at_kst": datetime.now().strftime("%Y-%m-%d"),
        "flood_source": "https://portal.esrikr.com/arcgis/rest/services/Hosted/Flood_2002_2022/FeatureServer",
        "flood_source_approval": "https://www.safetydata.go.kr/disaster-data/view?dataSn=108",
        "rain_source": "https://apihub.kma.go.kr/apiList.do?seqApi=2&seqApiSub=239 (AWS 시간통계, var=RN)",
        "flood_record_count": len(features),
        "flood_event_count": len(event_rows),
        "storm_group_count": storm_group_count,
        "flood_year_range": (
            [min(valid_years), max(valid_years)]
            if (valid_years := [r["fldn_yr"] for r in event_rows if r["fldn_yr"]])
            else []
        ),
        "hourly_timestamps_fetched": len(cache),
        "event_rain_rows": rows_written,
        "inputs": {
            str(RAW_GEOJSON.relative_to(ROOT)): {"sha256": sha256_of(RAW_GEOJSON)},
        },
        "outputs": {
            str(RECORDS_CSV.relative_to(ROOT)): {"sha256": sha256_of(RECORDS_CSV)},
            str(EVENTS_CSV.relative_to(ROOT)): {"sha256": sha256_of(EVENTS_CSV)},
            str(EVENT_RAIN_CSV.relative_to(ROOT)): {"sha256": sha256_of(EVENT_RAIN_CSV)},
        },
        "critical_limitations": [
            "The flood layer stops at 2021 (2022 Typhoon Hinnamno is not in this dataset); the source agency has stopped updating it.",
            "fldn_bgng_tm is survey-estimated and rounded to the hour; some records read 0000, which may mean midnight or an unrecorded time, not necessarily verified.",
            "This output is event x station data. The downstream training-table script selects the nearest eligible station for each building and records rain_station_distance_km.",
            "Rainfall windows are populated only when every expected hourly value exists; inspect hours_available_1h/3h/6h/12h/24h for coverage.",
            "storm_group_id conservatively merges all event timestamps on the same or consecutive dates so one storm is not split across model folds; it remains a derived grouping, not an official disaster identifier.",
            "Geometry (GEOM) was dropped from gyeongbuk_flood_records.csv; use the source GeoJSON for spatial joins against building polygons.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[check] wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
