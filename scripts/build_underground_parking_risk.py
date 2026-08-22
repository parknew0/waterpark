#!/usr/bin/env python3
"""Score every Gyeongbuk underground-parking building for flood risk.

Why this is rule-based and not a model
--------------------------------------
train_flood_model.py showed the honest result: split by rainfall event, XGBoost
reaches PR-AUC ~0.09 against a 0.065 base rate, while the single terrain rule
"lower ground relative to its surroundings floods more" reaches ~0.25 with no
fitting at all. With only 21 events carrying positives, and rainfall constant
across all buildings inside one event, there is no rain-to-flood relationship
left to learn. So terrain is measured from our own data, and the rainfall
trigger comes from the official KMA 호우특보 thresholds instead of being learnt.

Two separate things are produced per building:

* ``terrain_risk`` -- static, from the ground. Valid regardless of weather.
* ``rain_trigger_*`` -- the official rainfall level at which that terrain risk
  should be acted on. The live service applies this against current rainfall.

Deliberately NOT claimed: that the underground car park itself floods. The
survey behind these numbers recorded surface flooding only.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
BUILDINGS_CSV = ROOT / "data/processed/gyeongbuk_building_underground_parking_features.csv"
OVERTURE_GZ = ROOT / "data/processed/gyeongbuk_buildings_elevation.csv.gz"
FLOOD_GEOJSON = ROOT / "data/raw/flood-trace/gyeongbuk_flood_2002_2022.geojson"

OUT_CSV = ROOT / "data/processed/gyeongbuk_underground_parking_risk.csv"
OUT_DIR = ROOT / "outputs/gyeongbuk-parking-risk"
MANIFEST = OUT_DIR / "manifest.json"
SAMPLE = OUT_DIR / "gyeongbuk_underground_parking_risk_sample.csv"

# Observed surface-flood rate by height above the local 1 km minimum, measured
# on gyeongbuk_flood_training_table.csv (45,886 rows, 6.50% base rate).
# (upper bound in metres, label, observed flood rate, lift vs base rate)
TERRAIN_BANDS = [
    (2.0, "VERY_HIGH", 0.355, 5.5),
    (5.0, "HIGH", 0.148, 2.3),
    (10.0, "MODERATE", 0.052, 0.8),
    (20.0, "LOW", 0.004, 0.1),
    (float("inf"), "VERY_LOW", 0.000, 0.0),
]

# Official KMA 호우특보 / 극한호우 criteria. Source: 기상청 예보업무 안내
# (kma.go.kr/kma/biz/forecast03.jsp) and the 2023-06-15 극한호우 직접 발송 기준.
# These are NOT fitted to our data -- our 21 events carry no usable rain signal.
RAIN_RULES = {
    "호우주의보": "3시간 60mm 이상 또는 12시간 110mm 이상",
    "호우경보": "3시간 90mm 이상 또는 12시간 180mm 이상",
    "극한호우": "1시간 50mm 이상이면서 3시간 90mm 이상, 또는 1시간 72mm 이상",
}
# Which official level should trigger action for each terrain band.
TERRAIN_TO_TRIGGER = {
    "VERY_HIGH": "호우주의보",
    "HIGH": "호우주의보",
    "MODERATE": "호우경보",
    "LOW": "극한호우",
    "VERY_LOW": "극한호우",
}

DEG = 1.0 / 111000.0
MAX_ELEVATION_MATCH_M = 100.0  # beyond this the borrowed DSM cell is not the same ground


def log(m: str) -> None:
    print(m, flush=True)


def terrain_band(rel_elev: float | None):
    if rel_elev is None or math.isnan(rel_elev):
        return "UNKNOWN", None, None
    for upper, label, rate, lift in TERRAIN_BANDS:
        if rel_elev <= upper:
            return label, rate, lift
    return "UNKNOWN", None, None


def combined_risk(terrain: str, flood_dist_m: float | None) -> str:
    """Static flood likelihood, before live rainfall is applied.

    Only evidence about how likely water is to arrive belongs here. Whether the
    building has underground parking, and how many cars are in it, is
    consequence rather than likelihood -- those stay in their own columns so the
    service can rank by impact without this number quietly absorbing them.
    """
    order = ["VERY_LOW", "LOW", "MODERATE", "HIGH", "VERY_HIGH"]
    if terrain == "UNKNOWN":
        return "UNKNOWN"
    idx = order.index(terrain)
    # An official survey having found water right next to this building is
    # direct evidence, so it raises the likelihood by one band.
    if flood_dist_m is not None and flood_dist_m <= 500:
        idx = min(idx + 1, len(order) - 1)
    return order[idx]


def main() -> None:
    for p in (BUILDINGS_CSV, OVERTURE_GZ, FLOOD_GEOJSON):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")

    blds = list(csv.DictReader(BUILDINGS_CSV.open(encoding="utf-8-sig")))
    log(f"[check] {len(blds):,} underground-floor buildings to score")

    # ---- borrow elevation from the nearest Overture building ------------
    # The model and these bands were both built on Overture's DSM features, so
    # borrowing keeps the feature definition identical rather than recomputing
    # a slightly different 'relative elevation' from raw DEM.
    ov_pts, ov_vals = [], []
    with gzip.open(OVERTURE_GZ, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                lon, lat = float(r["longitude"]), float(r["latitude"])
                elev = float(r["surface_elevation_m"])
                rel = float(r["relative_elevation_to_local_building_min_m"])
            except (KeyError, ValueError, TypeError):
                continue
            ov_pts.append(Point(lon, lat))
            ov_vals.append((elev, rel))
    log(f"[check] {len(ov_pts):,} Overture buildings available as elevation donors")
    ov_tree = STRtree(ov_pts)

    # ---- historical flood polygons --------------------------------------
    feats = json.loads(FLOOD_GEOJSON.read_text(encoding="utf-8"))["features"]
    polys = [shape(f["geometry"]) for f in feats]
    flood_union = unary_union(polys)
    log(f"[check] {len(polys):,} historical flood polygons loaded")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    header = [
        "building_id",
        "pnu",
        "building_name",
        "legal_dong_name",
        "lot_number",
        "longitude",
        "latitude",
        "underground_parking_status",
        "underground_parking_confirmed",
        "underground_floor_count_gis",
        "indoor_parking_slots_max",
        "main_purpose_name",
        "surface_elevation_m",
        "relative_elevation_m",
        "elevation_match_distance_m",
        "terrain_risk",
        "terrain_observed_flood_rate",
        "terrain_lift_vs_average",
        "distance_to_past_flood_m",
        "inside_past_flood_area",
        "static_risk",
        "rain_trigger_level",
        "rain_trigger_rule",
    ]

    stats = Counter()
    risk_counts = Counter()
    far_match = 0
    written = 0

    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for b in blds:
            lon, lat = float(b["longitude"]), float(b["latitude"])
            pt = Point(lon, lat)

            # nearest Overture donor
            j = ov_tree.nearest(pt)
            donor = ov_pts[j]
            match_m = math.hypot((donor.x - lon) * 88800, (donor.y - lat) * 111000)
            if match_m > MAX_ELEVATION_MATCH_M:
                far_match += 1
                elev = rel = None
            else:
                elev, rel = ov_vals[j]

            band, rate, lift = terrain_band(rel)
            stats[band] += 1

            d_flood = flood_union.distance(pt) / DEG
            inside = flood_union.contains(pt)
            if inside:
                d_flood = 0.0

            risk = combined_risk(band, d_flood)
            risk_counts[risk] += 1
            trigger = TERRAIN_TO_TRIGGER.get(band, "호우경보")

            w.writerow(
                [
                    b["building_id"],
                    b["pnu"],
                    b["building_name"],
                    b["legal_dong_name"],
                    b["lot_number"],
                    round(lon, 7),
                    round(lat, 7),
                    b["underground_parking_status"],
                    b["underground_parking_confirmed"],
                    b["underground_floor_count_gis"],
                    b["indoor_parking_slots_max"],
                    b["main_purpose_name"],
                    round(elev, 2) if elev is not None else "",
                    round(rel, 2) if rel is not None else "",
                    round(match_m, 1),
                    band,
                    rate if rate is not None else "",
                    lift if lift is not None else "",
                    round(d_flood, 1),
                    1 if inside else 0,
                    risk,
                    trigger,
                    RAIN_RULES.get(trigger, ""),
                ]
            )
            written += 1

    log(f"\n[check] wrote {OUT_CSV.relative_to(ROOT)} ({written:,} rows)")
    log("[check] terrain risk distribution:")
    for k, v in stats.most_common():
        log(f"          {v:6,}  {k}")
    log("[check] static risk distribution:")
    for k, v in risk_counts.most_common():
        log(f"          {v:6,}  {k}")
    if far_match:
        log(f"[warn] {far_match} buildings had no Overture donor within {MAX_ELEVATION_MATCH_M:.0f} m")

    with OUT_CSV.open(encoding="utf-8") as src, SAMPLE.open("w", encoding="utf-8") as dst:
        for i, line in enumerate(src):
            if i > 500:
                break
            dst.write(line)

    MANIFEST.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "rows": written,
                "method": "rule-based; terrain bands measured from our own flood training table, "
                "rainfall trigger taken from official KMA 호우특보 criteria",
                "terrain_bands": [
                    {
                        "max_relative_elevation_m": None if math.isinf(u) else u,
                        "label": l,
                        "observed_flood_rate": r,
                        "lift_vs_base_rate": lf,
                    }
                    for u, l, r, lf in TERRAIN_BANDS
                ],
                "base_flood_rate_in_training_table": 0.065,
                "rain_rules_official": RAIN_RULES,
                "terrain_to_trigger": TERRAIN_TO_TRIGGER,
                "terrain_risk_counts": dict(stats),
                "static_risk_counts": dict(risk_counts),
                "elevation_donor": "nearest Overture building (same DSM feature definition)",
                "elevation_match_limit_m": MAX_ELEVATION_MATCH_M,
                "buildings_without_elevation_donor": far_match,
                "critical_limitations": [
                    "terrain_risk predicts SURFACE flooding at the building, not flooding of "
                    "the underground car park itself. No dataset records the latter.",
                    "Observed flood rates come from areas within 1 km of a surveyed flood "
                    "polygon, so they describe flood-prone neighbourhoods, not all Gyeongbuk.",
                    "The rainfall trigger is an official warning threshold, not a fitted "
                    "probability. It says when to act, not how likely flooding is.",
                    "Elevation is a Copernicus GLO-30 DSM including buildings and canopy, "
                    "borrowed from the nearest Overture building.",
                    "underground_parking_status is parcel-level, so buildings sharing a parcel "
                    "share the flag.",
                    "The flood survey ends in 2021 and mostly covered farmland and river "
                    "plains, so urban districts such as 경산 have no historical record at all. "
                    "distance_to_past_flood_m being large is not evidence of safety.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log(f"[check] wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
