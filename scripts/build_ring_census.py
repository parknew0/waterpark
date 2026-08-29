#!/usr/bin/env python3
"""Every cell the survey walked, counted -- not sampled.

A matched case-control set fixes the ratio of floods to controls by design, so
the percentages read off it are the design's, not the world's. "73% of low
ground floods" is then meaningless, and the rain axis can even run backwards
when the event mix shifts between bins.

Counting instead of sampling fixes that. Around each recorded flood, every
100 m cell out to 2 km is taken, once: cells holding a record for this storm
are the floods, cells beyond the ambiguous inner band are the dry ground, and
the ratio between them is the real one. Rain comes from the nearest point the
radar was sampled at -- the radar puts that error at 1% within 500 m and 7%
within a kilometre.

The inner band exists because a cell 200 m from a recorded flood was probably
under the same water and merely never written down. Counting it as dry would
teach exactly the wrong lesson.
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
from projection import wgs84_to_grid  # noqa: E402

TERRAIN = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "rel_2000m", "slope_deg"]
WINDOWS = (1, 3, 6, 12, 24)


def to_cells(lons, lats, meta):
    rr = np.empty(len(lons), dtype=np.int64)
    cc = np.empty(len(lons), dtype=np.int64)
    for i, (lo, la) in enumerate(zip(lons, lats)):
        x, y = wgs84_to_grid(lo, la)
        rr[i] = int((meta["origin_y_top"] - y) // meta["cell_m"])
        cc[i] = int((x - meta["origin_x"]) // meta["cell_m"])
    return rr, cc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-dir", type=Path, default=ROOT / "data/interim/radar/events")
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--anchor-hours", type=Path, required=True)
    parser.add_argument("--outer-cells", type=int, default=20, help="2 km at 100 m cells")
    parser.add_argument("--inner-cells", type=int, default=3, help="애매한 안쪽 띠")
    parser.add_argument("--rain-max-m", type=float, default=1000.0)
    parser.add_argument("--drop-river", type=Path,
                        help="하천범람으로 분류된 침수점을 뺀다(flood_cause.csv)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bett", ROOT / "scripts/build_event_training_table.py")
    bett = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bett)

    anchors = {k: v for k, v in
               json.loads(args.anchor_hours.read_text(encoding="utf-8")).items()
               if v is not None}
    _t = np.load(ROOT / "data/interim/hydro/grid_terrain.npz")
    terrain = {n: _t[n] for n in TERRAIN}
    above_river = np.load(ROOT / "data/processed/risk-grid/risk_grid.npz")[
        "elev_above_national_river"]
    # Land use turned out to be the only genuinely new axis this project found:
    # the same low ground sheds or absorbs depending on what covers it.
    built = np.load(ROOT / "data/interim/hydro/grid_built.npz")
    landc = np.load(ROOT / "data/interim/hydro/grid_landcover_5179.npz")
    extra = {"built_ratio": built["built_ratio"], "built_count": built["built_count"],
             "impervious": landc["impervious"], "water_frac": landc["water"]}
    meta = json.loads((ROOT / "data/processed/serving-bundle/grid_meta.json")
                      .read_text(encoding="utf-8"))["grid"]
    n_rows, n_cols = terrain["elevation"].shape

    pts = pd.read_csv(args.points, dtype={"event": str})
    pts["event"] = pts["event"].fillna("")
    floods = pts[pts.kind == "flood"]
    # River overflow is decided upstream: the gauge that matters is the river's
    # stage, not the rain underfoot. Counting it here inflates the rate for
    # low riverside ground at rainfalls that never touched it.
    if args.drop_river:
        cause = pd.read_csv(args.drop_river, dtype={"event": str})
        river = {(round(r.lon, 5), round(r.lat, 5), r.event)
                 for r in cause.itertuples() if r.river is True}
        keep = [not (round(r.lon, 5), round(r.lat, 5), r.event) in river
                for r in floods.itertuples()]
        before = len(floods)
        floods = floods[keep]
        print(f"[원인] 하천범람 {before - len(floods):,}건 제외 -> 침수점 {len(floods):,}", flush=True)
    fr, fc = to_cells(floods.lon.to_numpy(), floods.lat.to_numpy(), meta)
    floods = floods.assign(row=fr, col=fc)

    R = args.outer_cells
    dy, dx = np.mgrid[-R:R + 1, -R:R + 1]
    disk = (dy**2 + dx**2) <= R**2
    dy, dx = dy[disk], dx[disk]

    frames = []
    for path in sorted(args.radar_dir.glob("rain_*.npz")):
        event = path.stem.replace("rain_", "")
        data = np.load(path)
        if "lon" not in data or event not in anchors:
            continue
        case = floods[floods.event == event]
        if len(case) == 0:
            continue

        spans = (data["span_min"].astype("float64") if "span_min" in data
                 else np.full(data["series"].shape[0], float(data["step_min"])))
        end = len(spans)
        cut = bett.first_after(data["stamps"], event, anchors[event])
        if cut is not None and cut >= 2:
            end = cut
        totals = bett.accumulate(data["series"][:end], spans[:end], forward=False)
        sampled = cKDTree(np.c_[data["lon"] * 88_000, data["lat"] * 111_000])

        # union of the disks, counted once each
        cells = np.unique(((case.row.to_numpy()[:, None] + dy) * n_cols
                           + (case.col.to_numpy()[:, None] + dx)).ravel())
        rr, cc = cells // n_cols, cells % n_cols
        ok = (rr >= 0) & (rr < n_rows) & (cc >= 0) & (cc < n_cols)
        rr, cc = rr[ok], cc[ok]

        # distance in cells to the nearest flood record of any storm
        ftree = cKDTree(np.c_[floods.row, floods.col])
        dist_any = ftree.query(np.c_[rr, cc], k=1)[0]
        # ... and to this storm's own records, which is what makes a cell a case
        ctree = cKDTree(np.c_[case.row, case.col])
        dist_own = ctree.query(np.c_[rr, cc], k=1)[0]

        flooded = dist_own < 1.0                      # 이 사건의 기록이 있는 칸
        ambiguous = (~flooded) & (dist_any <= args.inner_cells)
        keep = flooded | (~ambiguous)
        rr, cc, flooded = rr[keep], cc[keep], flooded[keep]

        elev = terrain["elevation"][rr, cc]
        land = np.isfinite(elev) & (elev > 0)         # 바다는 0으로 기록된다
        rr, cc, flooded = rr[land], cc[land], flooded[land]

        lon = meta["origin_x"] + (cc + 0.5) * meta["cell_m"]
        lat = meta["origin_y_top"] - (rr + 0.5) * meta["cell_m"]
        # projected metres -> the KD-tree above is in the same rough scaling
        from projection import grid_to_wgs84
        ll = np.array([grid_to_wgs84(x, y) for x, y in zip(lon, lat)])
        dist, near = sampled.query(np.c_[ll[:, 0] * 88_000, ll[:, 1] * 111_000], k=1)
        near_ok = dist <= args.rain_max_m
        rr, cc, flooded, ll, near = rr[near_ok], cc[near_ok], flooded[near_ok], ll[near_ok], near[near_ok]

        frame = {"event": event, "lon": ll[:, 0].round(6), "lat": ll[:, 1].round(6),
                 "flooded": flooded.astype(int)}
        for n in TERRAIN:
            frame[n] = terrain[n][rr, cc]
        frame["above_river"] = above_river[rr, cc]
        for n, arr in extra.items():
            frame[n] = arr[rr, cc]
        for h in WINDOWS:
            frame[f"rain_{h}h"] = totals[h][near]
        df = pd.DataFrame(frame)
        df = df[np.isfinite(df[TERRAIN + ["rain_24h"]]).all(axis=1)]
        frames.append(df)
        print(f"  {event}: 칸 {len(df):,}  침수 {int(df.flooded.sum()):,} "
              f"({df.flooded.mean()*100:.2f}%)", flush=True)

    out = pd.concat(frames, ignore_index=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"\n[결과] {len(out):,}칸  침수 {int(out.flooded.sum()):,} "
          f"({out.flooded.mean()*100:.2f}%) -> {args.out}")


if __name__ == "__main__":
    main()
