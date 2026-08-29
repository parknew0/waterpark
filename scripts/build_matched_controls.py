#!/usr/bin/env python3
"""Controls from where the survey went, not from the whole country.

The national random controls sit 57 m above their surroundings while flood
sites sit at 8 m, so the terrain axis reads backwards: the flattest ground
comes out safest. The gap is not physics, it is who got looked at -- the trace
survey walks the ground that went under and never climbs the hill behind it.

So each flood point gets its own controls, drawn from a ring around it: far
enough out that they are not the same puddle, close enough in that the same
crew would have walked past them. Their rain is borrowed from the nearest point
the radar was already sampled at, which the radar itself says is safe -- 6-hour
totals differ by 1% within 500 m and 7% within a kilometre, against the 41% a
gauge 8 km away would be off by.

The inner radius matters. A cell 100 m from a recorded flood was probably under
the same water and simply never written down; counting it as dry teaches the
model that low ground is safe.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "serverless"))
from projection import grid_to_wgs84, wgs84_to_grid  # noqa: E402

TERRAIN = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "rel_2000m", "slope_deg"]
WINDOWS = (1, 3, 6, 12, 24)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-dir", type=Path, default=ROOT / "data/interim/radar/events")
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--anchor-hours", type=Path, required=True)
    parser.add_argument("--inner-m", type=float, default=300.0)
    parser.add_argument("--outer-m", type=float, default=2000.0)
    parser.add_argument("--per-case", type=int, default=4)
    parser.add_argument("--rain-max-m", type=float, default=1000.0,
                        help="이 거리 안에 표본 지점이 없으면 그 대조점은 버린다")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bett", ROOT / "scripts/build_event_training_table.py")
    bett = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bett)

    anchors = {k: v for k, v in
               json.loads(args.anchor_hours.read_text(encoding="utf-8")).items()
               if v is not None}
    # Indexing an NpzFile decompresses the whole array every time, so the
    # per-row lookups below have to read from real arrays, not from the archive.
    _t = np.load(ROOT / "data/interim/hydro/grid_terrain.npz")
    terrain = {n: _t[n] for n in TERRAIN}
    _g = np.load(ROOT / "data/processed/risk-grid/risk_grid.npz")
    above_river = _g["elev_above_national_river"]
    meta = json.loads((ROOT / "data/processed/serving-bundle/grid_meta.json")
                      .read_text(encoding="utf-8"))["grid"]
    rows_n, cols_n = terrain["elevation"].shape

    # Event ids are dates, not numbers: read as float and 20220808 becomes
    # "20220808.0", which matches nothing.
    pts = pd.read_csv(args.points, dtype={"event": str})
    pts["event"] = pts["event"].fillna("")
    flood_all = pts[pts.kind == "flood"]
    # Every recorded flood, whatever storm it belongs to, blocks its
    # neighbourhood: a place that drowned in 2020 and again in 2022 is not a
    # control for either.
    block = cKDTree(np.c_[flood_all.lon * 88_000, flood_all.lat * 111_000])

    rng = np.random.default_rng(20260825)
    out_rows = []
    for path in sorted(args.radar_dir.glob("rain_*.npz")):
        event = path.stem.replace("rain_", "")
        data = np.load(path)
        if "lon" not in data or event not in anchors:
            continue
        cases = pts[(pts.kind == "flood") & (pts.event == event)]
        if len(cases) == 0:
            continue

        spans = (data["span_min"].astype("float64") if "span_min" in data
                 else np.full(data["series"].shape[0], float(data["step_min"])))
        end = len(spans)
        cut = bett.first_after(data["stamps"], event, anchors[event])
        if cut is not None and cut >= 2:
            end = cut
        totals = bett.accumulate(data["series"][:end], spans[:end], forward=False)
        sampled = cKDTree(np.c_[data["lon"] * 88_000, data["lat"] * 111_000])

        # ring around each case
        k = args.per_case
        angle = rng.uniform(0, 2 * np.pi, (len(cases), k))
        # uniform over the annulus, not over the radius
        rad = np.sqrt(rng.uniform(args.inner_m**2, args.outer_m**2, (len(cases), k)))
        lon0 = np.repeat(cases.lon.to_numpy()[:, None], k, axis=1)
        lat0 = np.repeat(cases.lat.to_numpy()[:, None], k, axis=1)
        lon = (lon0 + rad * np.cos(angle) / 88_000).ravel()
        lat = (lat0 + rad * np.sin(angle) / 111_000).ravel()

        keep = block.query(np.c_[lon * 88_000, lat * 111_000], k=1)[0] >= args.inner_m
        lon, lat = lon[keep], lat[keep]
        dist, near = sampled.query(np.c_[lon * 88_000, lat * 111_000], k=1)
        keep = dist <= args.rain_max_m
        lon, lat, near = lon[keep], lat[keep], near[keep]

        rr = np.empty(len(lon), dtype=int)
        cc = np.empty(len(lon), dtype=int)
        for i, (x_, y_) in enumerate(zip(lon, lat)):
            x, y = wgs84_to_grid(x_, y_)
            rr[i] = int((meta["origin_y_top"] - y) // meta["cell_m"])
            cc[i] = int((x - meta["origin_x"]) // meta["cell_m"])
        ok = (rr >= 0) & (rr < rows_n) & (cc >= 0) & (cc < cols_n)
        rr, cc, lon, lat, near = rr[ok], cc[ok], lon[ok], lat[ok], near[ok]
        elev = terrain["elevation"][rr, cc]
        # Sea is written as exactly 0 in the DSM and is not dry land that failed
        # to flood.
        ok = np.isfinite(elev) & (elev > 0)
        rr, cc, lon, lat, near = rr[ok], cc[ok], lon[ok], lat[ok], near[ok]

        for i in range(len(rr)):
            row = {"event": event, "lon": round(float(lon[i]), 6),
                   "lat": round(float(lat[i]), 6), "flooded": 0}
            bad = False
            for n in TERRAIN:
                v = terrain[n][rr[i], cc[i]]
                if not np.isfinite(v):
                    bad = True
                    break
                row[n] = round(float(v), 2)
            if bad:
                continue
            v = above_river[rr[i], cc[i]]
            row["above_river"] = "" if not np.isfinite(v) else round(float(v), 2)
            if not np.isfinite(totals[24][near[i]]):
                continue
            for h in WINDOWS:
                row[f"rain_{h}h"] = round(float(totals[h][near[i]]), 2)
            out_rows.append(row)
        print(f"  {event}: 침수 {len(cases):,} -> 대조 {len(out_rows):,}(누적)", flush=True)

    fields = (["event", "lon", "lat", "flooded"] + TERRAIN + ["above_river"]
              + [f"rain_{h}h" for h in WINDOWS])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out_rows)[fields].to_csv(args.out, index=False)
    print(f"\n[결과] 대조점 {len(out_rows):,}행 -> {args.out}")


if __name__ == "__main__":
    main()
