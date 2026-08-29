#!/usr/bin/env python3
"""One row per (place, storm): terrain, the rain that fell, and the outcome.

Until now terrain and rainfall lived in separate halves of the service. The
model ranked ground by how often it floods and knew nothing about weather; a
fixed national threshold — 호우경보 at 90 mm over three hours — decided when to
act. That threshold is the same in a river-mouth basin and on a hillside, when
the whole point is that they do not flood at the same depth of rain.

Joining them needs a row that carries both, and an outcome that was observed
under that specific rain. The radar series supplies accumulations ending at the
observed flood time; the terrain grid supplies the same columns the standing
model uses.

Controls are drawn from the same storms, not from fair weather: a place that
stayed dry while 80 mm fell on it is the only evidence that separates "low
ground" from "low ground that floods".
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "serverless"))
from projection import wgs84_to_grid  # noqa: E402

WINDOWS = (1, 3, 6, 12, 24)
EXTRA = ("rain_peak", "rain_peak_1h", "rain_prior", "rain_hours")


def first_after(stamps, event: str, hour: float) -> int | None:
    """Index of the first frame later than the flood hour, or None."""
    want = f"{event}{int(hour):02d}00"
    for j, stamp in enumerate(stamps):
        if str(stamp) > want:
            return j
    return None


def accumulate(series: np.ndarray, spans: np.ndarray, forward: bool) -> dict:
    """Span-weighted rain totals over each window, from one end of the series.

    Each frame stands for its own span, so a 60-minute frame counts six times a
    10-minute one. A dropped frame is dropped from both sides of the average
    rather than being read as an hour of no rain.
    """
    covered = np.cumsum(spans) if forward else np.cumsum(spans[::-1])[::-1]
    totals = {}
    for hours in WINDOWS:
        take = covered <= hours * 60
        if not take.any():
            take = np.zeros(len(spans), bool)
            take[0 if forward else -1] = True
        window, weights = series[take], spans[take]
        good = np.isfinite(window)
        wsum = (np.where(good, window, 0.0) * weights[:, None]).sum(axis=0)
        wtot = (good * weights[:, None]).sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            rate = np.where(wtot > 0, wsum / wtot, np.nan)
        totals[hours] = rate * hours
    return totals


def extra_rain(series: np.ndarray, spans: np.ndarray) -> dict:
    """Shape of the storm, not just how much of it fell.

    Two places can receive the same 6-hour total and drown differently. What
    separates them is how hard it came -- drainage is sized for a rate, not a
    volume -- and whether the ground was already full when it started. Both are
    standard in flood hydrology and neither is recoverable from an accumulation
    ending at the flood hour, which is all the model had.
    """
    good = np.isfinite(series)
    rate = np.where(good, series, 0.0)                 # mm/h per frame
    out = {}
    out["rain_peak"] = rate.max(axis=0)                # 가장 센 순간의 강도
    # heaviest single hour anywhere in the window
    covered = np.cumsum(spans)
    hour = np.zeros(series.shape[1], dtype="float32")
    for i in range(len(spans)):
        j = np.searchsorted(covered, covered[i] + 60.0, side="right")
        if j <= i:
            continue
        w = spans[i:j]
        seg = rate[i:j]
        hour = np.maximum(hour, (seg * w[:, None]).sum(axis=0) / 60.0)
    out["rain_peak_1h"] = hour
    # rain that fell 24-48 h before the flood: the ground it landed on
    back = np.cumsum(spans[::-1])[::-1]
    older = (back > 24 * 60) & (back <= 48 * 60)
    if older.any():
        w = spans[older]
        out["rain_prior"] = (rate[older] * w[:, None]).sum(axis=0) / 60.0
    else:
        out["rain_prior"] = np.zeros(series.shape[1], dtype="float32")
    # how long it rained at all -- a long soak and a cloudburst differ
    out["rain_hours"] = ((rate > 1.0) * spans[:, None]).sum(axis=0) / 60.0
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-dir", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--window-mode", choices=("before", "after"),
                        default="before",
                        help="before=침수 전 비, after=침수 후 비(누수 시험용)")
    parser.add_argument("--anchor-hours", type=Path,
                        help="사건 -> 침수 시각(시). 주면 누적을 그 시각에서 끊는다")
    args = parser.parse_args()

    # Rain is only evidence for a flood if it fell before the water arrived.
    # Ending every accumulation at midnight puts hours of post-flood rain into
    # the window: the Gangnam flood began at 18:00, so a midnight window
    # carried six hours of rain that could not have caused it.
    anchors = {}
    if args.anchor_hours:
        anchors = {k: v for k, v in
                   json.loads(args.anchor_hours.read_text(encoding="utf-8")).items()
                   if v is not None}

    grid = np.load(ROOT / "data/processed/risk-grid/risk_grid.npz")
    terrain = np.load(ROOT / "data/interim/hydro/grid_terrain.npz")
    meta = json.loads((ROOT / "data/processed/serving-bundle/grid_meta.json")
                      .read_text(encoding="utf-8"))["grid"]

    # Flow accumulation and the wetness index derived from it are the standard
    # terrain predictors in flood hydrology, and every column above is a form
    # of "how high is this above something" -- none of them says how much water
    # arrives from upslope. They were computed and then never wired in.
    # v2 fixes routing: the first accumulation left depressions unfilled, so
    # D8 died at every one and half the country drained from nowhere.
    hydro = np.load(ROOT / "data/interim/hydro/grid_hydro_v2.npz")
    # What the ground is made of, not just its shape: a cell under buildings
    # sheds rain that a field would absorb.
    built = np.load(ROOT / "data/interim/hydro/grid_built.npz")
    # The ministry's land cover map, counted at 10 m: this is the measured
    # sealed fraction, not a bounding-box guess, and it sees roads and paved
    # yards that a building outline never will.
    land = np.load(ROOT / "data/interim/hydro/grid_landcover_5179.npz")
    names = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "rel_2000m", "slope_deg",
             "twi", "flow_acc", "sink_depth", "built_ratio", "built_count",
             "impervious", "water"]

    def locate(lons, lats):
        """Grid row/col for each point, plus which of them land on the grid."""
        rows_idx = np.empty(len(lons), dtype=int)
        cols_idx = np.empty(len(lons), dtype=int)
        for i, (lon, lat) in enumerate(zip(lons, lats)):
            x, y = wgs84_to_grid(lon, lat)
            rows_idx[i] = int((meta["origin_y_top"] - y) // meta["cell_m"])
            cols_idx[i] = int((x - meta["origin_x"]) // meta["cell_m"])
        inside = ((rows_idx >= 0) & (rows_idx < grid["risk_score"].shape[0])
                  & (cols_idx >= 0) & (cols_idx < grid["risk_score"].shape[1]))
        safe_r = np.clip(rows_idx, 0, grid["risk_score"].shape[0] - 1)
        safe_c = np.clip(cols_idx, 0, grid["risk_score"].shape[1] - 1)
        def source(n):
            if n in ("twi", "flow_acc", "sink_depth"):
                return hydro[n]
            if n in ("built_ratio", "built_count"):
                return built[n]
            if n in ("impervious", "water"):
                return land[n]
            return terrain[n]
        features = {n: source(n)[safe_r, safe_c].astype("float64") for n in names}
        features["above_river"] = grid["elev_above_national_river"][safe_r, safe_c]
        return inside, features

    out_rows = []
    for path in sorted(args.radar_dir.glob("rain_*.npz")):
        event = path.stem.replace("rain_", "")
        data = np.load(path)
        series = data["series"]                    # (frames, points)
        # Each file carries the points it was collected against. Two runs used
        # different point lists, and pairing a series with the wrong one lines
        # rain up against the terrain of somewhere else.
        if "lon" not in data:
            print(f"  {event}: 지점 좌표 없음 -> 건너뜀", flush=True)
            continue
        lons, lats = data["lon"], data["lat"]
        kinds, owners = data["kind"], data["owner"]
        if len(lons) != series.shape[1]:
            print(f"  {event}: 지점 {len(lons):,} != 열 {series.shape[1]:,} -> 건너뜀",
                  flush=True)
            continue
        inside, features = locate(lons, lats)
        # Older files carry one cadence; newer ones carry a span per frame
        # because the tail is sampled finely and the run-up coarsely.
        if "span_min" in data:
            spans = data["span_min"].astype("float64")
        else:
            spans = np.full(series.shape[0], float(data["step_min"]))


        # Rain is evidence for a flood only if it fell before the water came.
        # "before" ends the window at the flood hour; "after" starts there and
        # runs forward, which is rain that cannot have caused anything and so
        # measures how much the outcome leaks through the window alone.
        if args.window_mode == "after":
            if event not in anchors:
                print(f"  {event}: 침수 시각 없음 -> 건너뜀", flush=True)
                continue
            cut = first_after(data["stamps"], event, anchors[event])
            if cut is None or len(spans) - cut < 2:
                print(f"  {event}: 침수 이후 프레임이 부족 -> 건너뜀", flush=True)
                continue
            totals = accumulate(series[cut:], spans[cut:], forward=True)
        else:
            end = len(spans)
            if event in anchors:
                cut = first_after(data["stamps"], event, anchors[event])
                if cut is not None and cut >= 2:
                    end = cut
                else:
                    print(f"  {event}: 침수 시각 앞 프레임이 없음 -> 자정 기준 유지",
                          flush=True)
            totals = accumulate(series[:end], spans[:end], forward=False)
            shape = extra_rain(series[:end], spans[:end])

        for i in range(len(lons)):
            if not inside[i]:
                continue
            if kinds[i] == "flood" and owners[i] != event:
                continue                          # 다른 사건의 침수점은 이 사건의 대조가 아니다
            if not np.isfinite(features["rel_500m"][i]):
                continue
            if not np.isfinite(totals[24][i]):
                continue
            row = {
                "event": event,
                "lon": round(float(lons[i]), 6),
                "lat": round(float(lats[i]), 6),
                "flooded": 1 if kinds[i] == "flood" else 0,
            }
            for n in names + ["above_river"]:
                value = features[n][i]
                row[n] = "" if not np.isfinite(value) else round(float(value), 2)
            for hours in WINDOWS:
                row[f"rain_{hours}h"] = round(float(totals[hours][i]), 2)
            for n in EXTRA:
                row[n] = round(float(shape[n][i]), 2)
            out_rows.append(row)
        print(f"  {event}: 누적 {len(out_rows):,}행", flush=True)


    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = (["event", "lon", "lat", "flooded"] + names + ["above_river"]
              + [f"rain_{h}h" for h in WINDOWS] + list(EXTRA))
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
    positives = sum(r["flooded"] for r in out_rows)
    print(f"\n[결과] {len(out_rows):,}행  양성 {positives:,}  -> {args.out}")


if __name__ == "__main__":
    main()
