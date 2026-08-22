#!/usr/bin/env python3
"""Attach KMA hourly rainfall to Waterpark's Gyeongbuk flood-trace events.

Flood source: Esri Korea Living Atlas mirror of the official 행정안전부
침수흔적도 (2002-2022), approved via safetydata.go.kr dataSn=108.
    https://portal.esrikr.com/arcgis/rest/services/Hosted/Flood_2002_2022/FeatureServer

Rain source: KMA API Hub "AWS 시간통계 자료 조회" (awsh.php, var=RN), approved
application seqApi=2&seqApiSub=239.

This script only groups flood records into (date, start time) events and
attaches rain_1h/6h/24h per station. It does not join buildings or polygons
yet -- that needs the building/GIS join described in docs/01 and docs/02.
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

ROOT = Path(__file__).resolve().parents[1]
RAW_GEOJSON = ROOT / "data/raw/flood-trace/gyeongbuk_flood_2002_2022.geojson"
RAW_RAIN_JSONL = ROOT / "data/raw/kma-rain/gyeongbuk_flood_event_hourly_rain_raw.jsonl"
PROCESSED_DIR = ROOT / "data/processed"
OUTPUT_DIR = ROOT / "outputs/gyeongbuk-flood"
ENV_FILE = ROOT / ".env"

RECORDS_CSV = PROCESSED_DIR / "gyeongbuk_flood_records.csv"
EVENTS_CSV = PROCESSED_DIR / "gyeongbuk_flood_events.csv"
EVENT_RAIN_CSV = PROCESSED_DIR / "gyeongbuk_flood_event_rain.csv"
MANIFEST = OUTPUT_DIR / "manifest.json"
SAMPLE_CSV = OUTPUT_DIR / "gyeongbuk_flood_event_rain_sample.csv"

KMA_BASE = "https://apihub.kma.go.kr/api/typ01/url/awsh.php"
MISSING_BELOW = -90.0  # KMA uses -99 / -99.0 as the missing-value sentinel.


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

    non_gb = [f for f in features if f["properties"].get("stdg_ctpv_cd") != 47]
    if non_gb:
        print(f"[warn] {len(non_gb)} records are outside stdg_ctpv_cd=47 (Gyeongbuk) -- check the source export")

    # 1) flat records table (geometry dropped -- no geopandas/shapely available here)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    prop_keys = sorted({k for f in features for k in f["properties"].keys()})
    fieldnames = ["objectid"] + [k for k in prop_keys if k != "objectid"]
    with RECORDS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for f in features:
            writer.writerow(f["properties"])
    print(f"[check] wrote {RECORDS_CSV.relative_to(ROOT)} ({len(features)} rows)")

    # 2) group into (date, start time) events
    events = defaultdict(list)
    for f in features:
        p = f["properties"]
        events[(p["fldn_bgng_ymd"], p["fldn_bgng_tm"])].append(p)

    event_rows = []
    for (ymd, tm), props_list in sorted(events.items()):
        disaster_names = sorted({p["fldn_dst_nm"] for p in props_list})
        sgg_codes = sorted({p["stdg_sgg_cd"] for p in props_list})
        years = sorted({p["fldn_yr"] for p in props_list})
        event_rows.append(
            {
                "event_id": f"GB-{ymd}-{tm}",
                "fldn_bgng_ymd": ymd,
                "fldn_bgng_tm": tm,
                "fldn_yr": years[0] if years else "",
                "polygon_count": len(props_list),
                "sgg_codes": ";".join(str(s) for s in sgg_codes),
                "disaster_names": " | ".join(disaster_names),
            }
        )

    with EVENTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "event_id",
                "fldn_bgng_ymd",
                "fldn_bgng_tm",
                "fldn_yr",
                "polygon_count",
                "sgg_codes",
                "disaster_names",
            ],
        )
        writer.writeheader()
        writer.writerows(event_rows)
    print(f"[check] wrote {EVENTS_CSV.relative_to(ROOT)} ({len(event_rows)} distinct date+time events)")

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

    # 5) compute rain_1h / rain_6h / rain_24h per event per station
    all_stations = sorted({s for v in cache.values() for s in v.keys()})
    rows_written = 0
    rows_dropped_empty = 0
    with EVENT_RAIN_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "event_id",
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
                "hours_available_of_24",
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
                def window_sum(hours_back: int):
                    chunk = vals[:hours_back]
                    present = [v for v in chunk if v is not None]
                    return round(sum(present), 1) if present else None

                rain_1h = vals[0]
                writer.writerow(
                    [
                        row["event_id"],
                        row["fldn_bgng_ymd"],
                        row["fldn_bgng_tm"],
                        stn,
                        rain_1h,
                        window_sum(3),
                        window_sum(6),
                        window_sum(12),
                        window_sum(24),
                        len(available),
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
        "flood_year_range": [min(r["fldn_yr"] for r in event_rows), max(r["fldn_yr"] for r in event_rows)],
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
            "rain_1h/6h/24h are computed per AWS/ASOS station, not yet matched to buildings or to the flood polygon's location -- station selection per event still needs to happen.",
            "Older events (2002, 2008) may have few or no reporting AWS stations open at the time; check hours_available_of_24 before trusting a row.",
            "Geometry (GEOM) was dropped from gyeongbuk_flood_records.csv; use the source GeoJSON for spatial joins against building polygons.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[check] wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
