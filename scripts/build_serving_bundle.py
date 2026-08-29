#!/usr/bin/env python3
"""Assemble everything the Lambda needs into one deployable folder.

The runtime should carry exactly what it reads and nothing else.  The DSM is
768 MB, the river centreline 1.9 GB, and the building shapefiles 27 GB --
none of that belongs in a function package, because the grid already holds
their answers.

Four things go in:

    risk_grid.npz          precomputed terrain surface
    grid_meta.json         how to turn a coordinate into a cell index
    parking.json           the 1,233 confirmed underground car parks
    risk_bands.json        score cutoffs, measured rather than assumed

The band cutoffs are the part worth explaining.  A raw model score means
nothing to a reader, so it has to become a level, and the cutoffs come from
this grid's own score distribution rather than round numbers.  They are
quantiles of the surveyed area, so "상위 5%" means the same thing regardless
of how the model was rescaled by retraining.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from data_paths import ROOT

GRID_DIR = ROOT / "data/processed/risk-grid"
PARKING_CSV = ROOT / "data/interim/building-register/flooded_building_underground_parking.csv"
STATION_CSV = ROOT / "data/raw/kma-stations/kma_station_list.csv"
BUNDLE_DIR = ROOT / "data/processed/serving-bundle"
MANIFEST = ROOT / "outputs/flooded-building-register/serving_bundle.manifest.json"

# Percentile cutoffs over the surveyed area's own scores.  Levels are named
# for what the service does about them, not for the number behind them.
BAND_QUANTILES = [
    ("VERY_HIGH", 95.0),
    ("HIGH", 85.0),
    ("MODERATE", 60.0),
    ("LOW", 30.0),
]
# Terrain risk decides how little rain it takes to act, following the levels
# already fixed in docs/06. These are KMA's official thresholds, not fitted.
TRIGGER_BY_LEVEL = {
    "VERY_HIGH": "HEAVY_RAIN_ADVISORY",
    "HIGH": "HEAVY_RAIN_ADVISORY",
    "MODERATE": "HEAVY_RAIN_WARNING",
    "LOW": "EXTREME_RAIN",
    "VERY_LOW": "EXTREME_RAIN",
}


# 건축법 시행령 별표1 use classes, as they appear in the 건축HUB source.
# The service is English-language, so the bundle carries the translation and
# the runtime carries no lookup table. Anything unmapped passes through
# unchanged rather than being dropped, so a new source value stays visible
# instead of silently becoming blank.
BUILDING_USE_EN = {
    "공동주택": "Multi-family housing",
    "단독주택": "Detached house",
    "제1종근린생활시설": "Class 1 neighborhood facility",
    "제2종근린생활시설": "Class 2 neighborhood facility",
    "근린생활시설": "Neighborhood facility",
    "업무시설": "Office building",
    "숙박시설": "Lodging facility",
    "공장": "Factory",
    "의료시설": "Medical facility",
    "위락시설": "Amusement facility",
    "교육연구시설": "Education and research facility",
    "판매시설": "Retail facility",
    "자동차관련시설": "Automobile-related facility",
    "노유자시설": "Elderly and childcare facility",
    "문화및집회시설": "Culture and assembly facility",
    "종교시설": "Religious facility",
    "방송통신시설": "Broadcasting and telecommunications facility",
    "운동시설": "Sports facility",
}


def quantize_grid(grid: Any, destination: Path, surveyed_m: float) -> None:
    """Store the grid as integers rather than float32.

    float32 costs four bytes to carry precision nothing downstream uses.  The
    score only has to place a cell in one of five bands and shade a map, and
    the response already states it is a ranking score rather than a
    probability, so 1/254 steps are finer than the number means.  Elevations
    are reported to one decimal, so decimetres lose nothing either.

    Halving the payload also keeps the deployment package under the 10 MB
    ceiling for a browser upload, which is the difference between deploying
    from the console and needing S3 as an intermediate step.
    """
    risk = grid["risk_score"]
    valid = np.isfinite(risk)
    # 0 is reserved for nodata so a missing cell can never read as a real
    # score of zero; real scores occupy 1..255.
    risk_u8 = np.zeros(risk.shape, dtype="uint8")
    risk_u8[valid] = np.clip(np.round(risk[valid] * 254.0) + 1, 1, 255).astype("uint8")

    # The score ships nationwide; the evidence bands do not. The runtime only
    # quotes elevations where a flood record backs the reading up, and three
    # extra bands over 17.7 M cells is the difference between a package the
    # console accepts and one that needs S3. A present distance therefore
    # doubles as the runtime's test for "surveyed".
    inside = grid["dist_flood_m"] <= surveyed_m

    def to_decimetres(band: np.ndarray) -> np.ndarray:
        """Whole metres, carried in the decimetre encoding the runtime reads.

        The DSM is a 30 m product, so a tenth of a metre was never real
        precision. Rounding leaves far fewer distinct values to compress.
        """
        out = np.full(band.shape, np.iinfo("int16").min, dtype="int16")
        finite = np.isfinite(band) & inside
        out[finite] = np.clip(np.round(band[finite]) * 10.0, -32767, 32767).astype("int16")
        return out

    # 20 m steps: the cell is 100 m, so metre-level distance was never real.
    distance = np.full(grid["dist_flood_m"].shape, 65535, dtype="uint16")
    distance[inside] = (
        np.round(grid["dist_flood_m"][inside] / 20.0) * 20.0
    ).astype("uint16")

    np.savez_compressed(
        destination,
        risk_score_u8=risk_u8,
        rel_elev_500m_dm=to_decimetres(grid["rel_elev_500m"]),
        elev_above_national_river_dm=to_decimetres(grid["elev_above_national_river"]),
        dist_flood_m=distance,
    )


def build_bands(scores: np.ndarray) -> dict[str, Any]:
    finite = scores[np.isfinite(scores)]
    cutoffs = []
    for name, percentile in BAND_QUANTILES:
        cutoffs.append(
            {
                "level": name,
                "min_score": round(float(np.percentile(finite, percentile)), 6),
                "percentile": percentile,
                "rain_trigger": TRIGGER_BY_LEVEL[name],
            }
        )
    cutoffs.append(
        {
            "level": "VERY_LOW",
            "min_score": 0.0,
            "percentile": 0.0,
            "rain_trigger": TRIGGER_BY_LEVEL["VERY_LOW"],
        }
    )
    return {
        "bands": cutoffs,
        "scored_cells": int(finite.size),
        "note": (
            "Bands are quantiles of scores within the surveyed grid. They are not "
            "absolute probabilities and must be recalculated after retraining."
        ),
    }


def build_stations() -> dict[str, list[float]]:
    """Station id to coordinates, for locating the nearest rain gauge.

    The KMA hourly endpoint returns readings keyed by station id and no
    coordinates at all, so the service cannot tell which reading is nearest
    without this table.  The source lists a row per station per period, so
    later rows win and each station keeps its most recent position.
    """
    if not STATION_CSV.exists():
        raise SystemExit(f"관측소 목록이 없다: {STATION_CSV}")
    out: dict[str, list[float]] = {}
    with STATION_CSV.open(encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if len(row) < 8 or not row[0].strip().isdigit():
                continue
            try:
                out[row[0].strip()] = [round(float(row[6]), 5), round(float(row[7]), 5)]
            except ValueError:
                continue
    return out


def build_parking() -> list[dict[str, Any]]:
    """Confirmed underground car parks, trimmed to what the response shows."""
    if not PARKING_CSV.exists():
        raise SystemExit(f"지하주차장 확정 결과가 없다: {PARKING_CSV}")
    out = []
    with PARKING_CSV.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("underground_parking_confirmed") != "Y":
                continue
            try:
                lon = float(row["longitude"])
                lat = float(row["latitude"])
            except (TypeError, ValueError, KeyError):
                continue
            out.append(
                {
                    "pnu": row.get("pnu", ""),
                    "lon": round(lon, 6),
                    "lat": round(lat, 6),
                    "use": BUILDING_USE_EN.get(
                        (row.get("building_use_name") or "").strip(),
                        (row.get("building_use_name") or "").strip(),
                    ),
                    "ugFloors": int(row.get("underground_floor_count") or 0),
                    "approvalYear": row.get("approval_year", ""),
                }
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=BUNDLE_DIR)
    parser.add_argument(
        "--surveyed-radius-m",
        type=float,
        default=1800.0,
        help="이 거리 안에서만 지형 근거를 싣는다. 점수는 전국에 싣는다. "
        "serverless/handler.py 의 SURVEYED_RADIUS_M 와 같은 뜻이다.",
    )
    args = parser.parse_args()

    grid_path = GRID_DIR / "risk_grid.npz"
    grid_manifest = json.loads(
        (ROOT / "outputs/flooded-building-register/risk_grid.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if not grid_path.exists():
        raise SystemExit(f"격자가 없다: {grid_path}. build_risk_grid.py 먼저 실행한다.")

    args.out.mkdir(parents=True, exist_ok=True)
    grid = np.load(grid_path)
    quantize_grid(grid, args.out / "risk_grid.npz", args.surveyed_radius_m)
    bands = build_bands(grid["risk_score"])
    parking = build_parking()
    stations = build_stations()

    (args.out / "grid_meta.json").write_text(
        json.dumps(
            {
                "grid": grid_manifest["grid"],
                "bands": grid_manifest["bands"],
                "coverage": grid_manifest["coverage"],
                "encoding": {
                "risk_score_u8": "uint8. score = (v - 1) / 254. v=0은 미조사",
                "rel_elev_500m_dm": "int16 데시미터. m = v / 10. -32768은 결측",
                "elev_above_national_river_dm": "int16 데시미터. m = v / 10. -32768은 결측",
                "dist_flood_m": "uint16 미터. 65535는 미조사",
            },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.out / "risk_bands.json").write_text(
        json.dumps(bands, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out / "parking.json").write_text(
        json.dumps(parking, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (args.out / "stations.json").write_text(
        json.dumps(stations, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    sizes = {p.name: p.stat().st_size for p in sorted(args.out.iterdir()) if p.is_file()}
    total = sum(sizes.values())

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "bundle_dir": str(args.out.relative_to(ROOT)),
                "files": sizes,
                "total_bytes": total,
                "parking_count": len(parking),
                "station_count": len(stations),
                "bands": bands["bands"],
                "notes": [
                    "이 묶음만 Lambda에 올린다. DEM·하천·건물 원본은 올리지 않는다.",
                    "격자 밖 좌표는 UNKNOWN을 반환한다. 안전이 아니라 미조사다.",
                    "risk_score는 순위 점수다. 확률로 표기하면 안 된다.",
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[결과] 서빙 묶음 -> {args.out.relative_to(ROOT)}")
    for name, size in sizes.items():
        print(f"  {name:<20} {size / 1e6:>8.2f} MB")
    print(f"  {'합계':<20} {total / 1e6:>8.2f} MB")
    print(f"\n  지하주차장 {len(parking):,}동 / 관측소 {len(stations):,}곳")
    print("  위험 구간:")
    for band in bands["bands"]:
        print(f"    {band['level']:<10} score >= {band['min_score']:.4f}  → {band['rain_trigger']}")


if __name__ == "__main__":
    main()
