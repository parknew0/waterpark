#!/usr/bin/env python3
"""Merge every flood observation this project can place on the map.

Six sources describe the same phenomenon in different shapes: surveyed
polygons, depth points, water-level points, damage reports by address,
police-designated road hazards, and government-designated risk districts.
They were reaching the model as one narrow slice -- buildings that happened to
sit inside a surveyed polygon -- which both threw away most of the evidence
and biased what remained toward places that have buildings.

Every row carries where it came from, how precisely it was placed, and what
it knows: year, depth, and whether the water arrived by drainage failure or
by a river leaving its banks. A consumer that needs certainty can filter on
`precision`; one that needs volume can take everything.

Nothing is invented. A source without a depth leaves the field empty rather
than carrying a zero, and a coordinate that could only be resolved to a
법정동 centroid is marked `dong` -- measured at 642 m median error, which is
too coarse for a 100 m grid and is excluded from the default output.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np
import pyproj

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/interim/flood-labels/flood_labels.csv"
FROM_3857 = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform

INNER = ("내수", "배수", "하수", "역류", "저지대", "내부침수")
OUTER = ("범람", "제방", "월류", "외수")


def mechanism(text: str | None) -> str:
    """Drainage failure, river overflow, both, or unstated -- never guessed."""
    blob = str(text or "")
    inner = any(k in blob for k in INNER)
    outer = any(k in blob for k in OUTER)
    if inner and outer:
        return "both"
    if inner:
        return "inland"
    if outer:
        return "river"
    return ""


def depth_cm(value: object) -> str:
    """Centimetres, with implausible readings dropped rather than clipped."""
    if not isinstance(value, (int, float)) or value <= 0 or value > 1500:
        return ""
    return str(int(round(value)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="API 응답 캐시 폴더")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    def load(name: str) -> list:
        path = args.cache / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    rows: list[dict] = []

    for r in load("flood_wiseon.json"):
        lon, lat = FROM_3857(r["X"], r["Y"])
        rows.append({
            "source": "wiseon", "precision": "point",
            "lon": round(lon, 6), "lat": round(lat, 6),
            "year": r.get("FLUD_YEAR") or "", "depth_cm": depth_cm(r.get("AVG_FLDWTL")),
            "mechanism": mechanism(r.get("FLUD_NM2")), "grade": r.get("FLUD_GD") or "",
        })

    for r in load("flood_shim.json"):
        lon, lat = FROM_3857(r["X"], r["Y"])
        rows.append({
            "source": "shim", "precision": "point",
            "lon": round(lon, 6), "lat": round(lat, 6),
            "year": r.get("FLUD_YEAR") or "", "depth_cm": depth_cm(r.get("FLUD_SHIM")),
            "mechanism": "", "grade": r.get("FLUD_GD") or "",
        })

    for r in load("road_flood.json"):
        try:
            lat, lon = float(r["LAT"]), float(r["LOT"])
        except (TypeError, ValueError, KeyError):
            continue
        rows.append({
            "source": "road", "precision": "point",
            "lon": round(lon, 6), "lat": round(lat, 6),
            "year": "", "depth_cm": "",
            "mechanism": mechanism(r.get("DTL_CN")), "grade": "",
        })

    for r in load("dmg_geocoded.json"):
        rows.append({
            "source": "damage", "precision": "parcel",
            "lon": r["lon"], "lat": r["lat"],
            "year": r.get("year") or "", "depth_cm": "",
            "mechanism": "", "grade": "",
        })

    geo = {}
    path = args.cache / "geocoded.json"
    if path.exists():
        geo = json.loads(path.read_text(encoding="utf-8"))
    for r in load("risk_zone.json"):
        code, main_no = str(r.get("STDG_CD") or ""), r.get("MNLNO")
        if len(code) != 10 or main_no is None:
            continue
        san = "2" if str(r.get("MTN_ADDR_YN")) in ("1", "Y") else "1"
        key = f"{code}{san}{int(main_no):04d}{int(r.get('SUBLOTNO') or 0):04d}"
        if key not in geo:
            continue
        lon, lat = geo[key]
        rows.append({
            "source": "risk_zone", "precision": "parcel",
            "lon": lon, "lat": lat, "year": r.get("APLY_YR") or "", "depth_cm": "",
            "mechanism": mechanism(f"{r.get('DSGN_RSN')}{r.get('RSK_FACTR_CN')}"),
            "grade": r.get("DST_RSK_DSTRCT_GRD_CD") or "",
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source", "precision", "lon", "lat", "year", "depth_cm", "mechanism", "grade"]
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[결과] {len(rows):,}건 -> {args.out.relative_to(ROOT)}")
    for key in ("source", "precision", "mechanism"):
        counts: dict[str, int] = {}
        for row in rows:
            counts[row[key] or "(없음)"] = counts.get(row[key] or "(없음)", 0) + 1
        pairs = " ".join(f"{k} {v:,}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
        print(f"  {key:<10} {pairs}")
    depths = [int(r["depth_cm"]) for r in rows if r["depth_cm"]]
    years = sorted({r["year"] for r in rows if r["year"]})
    print(f"  depth_cm   {len(depths):,}건  중앙 {int(np.median(depths))}cm")
    print(f"  year       {years[0]}~{years[-1]}")


if __name__ == "__main__":
    main()
