#!/usr/bin/env python3
"""조사 범위 전수 조사를 30 m 격자에서 다시.

100 m판과 정의는 같다: 침수 기록 2 km 안의 칸을 한 번씩 모두 세고, 기록
바로 옆의 애매한 띠는 분모에서 뺀다. 달라지는 것은 한 칸이 축구장에서
도로 폭으로 줄었다는 것뿐이며, 그것이 지하차도와 골목을 볼 수 있느냐를
가른다.

비는 여전히 500 m 레이더에서 온다. 격자를 잘게 쪼개도 강수는 그만큼
선명해지지 않는다 -- 선명해지는 것은 '그 동네 안에서 물이 어디로 모이는가'
쪽이고, 그 쪽이 우리가 못 맞히던 부분이다.
"""
from __future__ import annotations
import argparse, importlib.util, json, sys, time
from pathlib import Path

import numpy as np
import pyproj
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
NX, NY = 2305, 2881
WINDOWS = (1, 3, 6, 12, 24)
LAYERS = ("elevation", "rel_200m", "rel_500m", "rel_1000m", "rel_2000m",
          "slope_deg", "flow_acc", "sink_depth", "built_ratio", "built_count",
          "impervious", "water",
          # 침수 논문이 표준으로 꼽는 인자들: 배수 갈래와 오목한 자리
          "drainage_density", "dist_stream", "curvature", "tpi_200m", "tpi_1000m",
          "dist_pump", "pump_capacity", "sewer_density")
STATUS = G30 / "census_status.json"


def args_poly_exists(a) -> bool:
    return bool(getattr(a, "polygons", None)) and a.polygons.exists()


def note(msg: str, frac: float | None = None) -> None:
    cur = {"message": msg, "updated": time.strftime("%H:%M:%S")}
    if frac is not None:
        cur["percent"] = round(frac * 100, 1)
    if STATUS.exists():
        try:
            old = json.loads(STATUS.read_text(encoding="utf-8"))
            cur["history"] = (old.get("history", []) + [f"{time.strftime('%H:%M')} {msg}"])[-25:]
        except Exception:
            cur["history"] = [msg]
    else:
        cur["history"] = [msg]
    STATUS.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    print(msg, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--radar-dir", type=Path, default=ROOT / "data/interim/radar/grids_full")
    ap.add_argument("--points", type=Path, default=ROOT / "config/radar/radar_points3.csv")
    ap.add_argument("--anchor-hours", type=Path, default=ROOT / "config/radar/flood_hours.json")
    ap.add_argument("--drop-river", type=Path,
                    default=ROOT / "data/interim/flood-labels/flood_cause.csv")
    ap.add_argument("--outer-m", type=float, default=2000.0)
    ap.add_argument("--inner-m", type=float, default=300.0)
    ap.add_argument("--polygons", type=Path,
                    default=ROOT / "data/interim/flood-labels/flood_cells30.npz",
                    help="면으로 칠한 침수 칸. 점 라벨은 옆 칸을 거짓 음성으로 만든다")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    import pandas as pd
    spec = importlib.util.spec_from_file_location(
        "bett", ROOT / "scripts/build_event_training_table.py")
    bett = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bett)
    spec2 = importlib.util.spec_from_file_location(
        "crr", ROOT / "scripts/collect_radar_rainfall.py")
    crr = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(crr)
    rate = crr.rain_rate

    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = g["rows"], g["cols"], g["cell_m"]
    OUTER = int(round(a.outer_m / cell))
    INNER = int(round(a.inner_m / cell))
    note(f"30 m 격자 {R:,} x {C:,}, 고리 {OUTER}칸(2 km), 안쪽 띠 {INNER}칸(300 m)", 0.0)

    anchors = {k: int(v) for k, v in
               json.loads(a.anchor_hours.read_text(encoding="utf-8")).items()
               if v is not None}
    pts = pd.read_csv(a.points, dtype={"event": str})
    pts["event"] = pts["event"].fillna("")
    floods = pts[pts.kind == "flood"].copy()
    if a.drop_river and a.drop_river.exists():
        cause = pd.read_csv(a.drop_river, dtype={"event": str})
        bad = {(round(r.lon, 5), round(r.lat, 5), r.event)
               for r in cause.itertuples() if r.river is True}
        keep = [not (round(r.lon, 5), round(r.lat, 5), r.event) in bad
                for r in floods.itertuples()]
        note(f"하천범람 {len(floods)-sum(keep):,}건 제외", 0.02)
        floods = floods[keep]

    to5179 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    to4326 = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    fx, fy = to5179.transform(floods.lon.values, floods.lat.values)
    floods["row"] = ((g["origin_y_top"] - fy) // cell).astype(np.int64)
    floods["col"] = ((fx - g["origin_x"]) // cell).astype(np.int64)

    note("레이더 좌표 색인 구축", 0.05)
    rlon = np.fromfile(ROOT / "data/interim/radar/hsr_lon.bin", dtype="<f4")[1:]
    rlat = np.fromfile(ROOT / "data/interim/radar/hsr_lat.bin", dtype="<f4")[1:]
    ok = np.isfinite(rlon) & np.isfinite(rlat) & (rlon > 120) & (rlon < 133)
    ridx = np.flatnonzero(ok)
    rtree = cKDTree(np.c_[rlon[ok] * 88_000, rlat[ok] * 111_000])

    polys = None
    if args_poly_exists(a):
        z = np.load(a.polygons)
        polys = {k[1:]: set(z[k].tolist()) for k in z.files if k.startswith("e")}
        note(f"폴리곤 라벨 {len(polys)}개 사건, 칸 "
             f"{sum(len(v) for v in polys.values()):,}", 0.06)

    layers = {n: np.load(G30 / f"{n}.npy", mmap_mode="r") for n in LAYERS}
    dy, dx = np.mgrid[-OUTER:OUTER + 1, -OUTER:OUTER + 1]
    disk = (dy**2 + dx**2) <= OUTER**2
    dy, dx = dy[disk].astype(np.int32), dx[disk].astype(np.int32)

    files = sorted(a.radar_dir.glob("rain_*_grid.npz"))
    # 사건마다 이어 쓴다. 마지막에 1,300만 행을 한 번에 concat 하면 메모리가
    # 두 배로 뛰어 다 만들어놓고 저장 직전에 죽는다.
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.out.exists():
        a.out.unlink()
    total = flooded_n = 0
    for n, path in enumerate(files):
        ev = path.stem.replace("rain_", "").replace("_grid", "")
        case = floods[floods.event == ev]
        if len(case) < 20 or ev not in anchors:
            continue
        z = np.load(path)
        stamps = z["stamps"]
        spans = z["span_min"].astype("float64")
        end = len(spans)
        cut = bett.first_after(stamps, ev, anchors[ev])
        if cut is not None and cut >= 2:
            end = cut
        grid = z["grid"][:end].astype("float32") / 100.0      # dBZ
        series = rate(grid).reshape(end, -1)                  # mm/h, (frames, cells)
        totals = bett.accumulate(series, spans[:end], forward=False)
        del grid, series

        # 이 사건의 침수 기록 주변 고리
        rows = (case.row.to_numpy()[:, None] + dy).ravel()
        cols = (case.col.to_numpy()[:, None] + dx).ravel()
        good = (rows >= 0) & (rows < R) & (cols >= 0) & (cols < C)
        keys = np.unique(rows[good].astype(np.int64) * C + cols[good])
        rr, cc = (keys // C).astype(np.int32), (keys % C).astype(np.int32)

        ftree = cKDTree(np.c_[floods.row.to_numpy(), floods.col.to_numpy()])
        ctree = cKDTree(np.c_[case.row.to_numpy(), case.col.to_numpy()])
        d_any = ftree.query(np.c_[rr, cc], k=1)[0]
        d_own = ctree.query(np.c_[rr, cc], k=1)[0]
        if polys is not None and ev in polys:
            # 면으로 칠한 칸이 곧 침수다. 점 기준(d_own<1)은 폴리곤 하나를
            # 한 칸으로 줄여 옆 칸 아홉을 거짓 음성으로 만든다.
            own = polys[ev]
            keys = rr.astype(np.int64) * C + cc
            flooded = np.fromiter((k in own for k in keys), bool, len(keys))
        else:
            flooded = d_own < 1.0
        keep = flooded | (d_any > INNER)
        rr, cc, flooded = rr[keep], cc[keep], flooded[keep]

        el = layers["elevation"][rr, cc]
        land = np.isfinite(el) & (el > 0)
        rr, cc, flooded = rr[land], cc[land], flooded[land]

        x = g["origin_x"] + (cc + 0.5) * cell
        y = g["origin_y_top"] - (rr + 0.5) * cell
        lon, lat = to4326.transform(x, y)
        near = rtree.query(np.c_[lon * 88_000, lat * 111_000], k=1)[1]
        cellidx = ridx[near]

        frame = {"event": ev, "flooded": flooded.astype(np.int8),
                 "lon": lon.astype("float32"), "lat": lat.astype("float32")}
        for nm in LAYERS:
            frame[nm] = np.asarray(layers[nm][rr, cc], dtype="float32")
        for h in WINDOWS:
            frame[f"rain_{h}h"] = totals[h][cellidx].astype("float32")
        df = pd.DataFrame(frame)
        df = df[np.isfinite(df[["elevation", "rel_500m", "rain_24h"]]).all(axis=1)]
        df.to_csv(a.out, mode="a", header=not a.out.exists(), index=False)
        total += len(df); flooded_n += int(df.flooded.sum())
        note(f"{ev}: 칸 {len(df):,}  침수 {int(df.flooded.sum()):,} "
             f"({df.flooded.mean()*100:.2f}%)", 0.05 + 0.9 * (n + 1) / len(files))

    note(f"완료 — {total:,}칸  침수 {flooded_n:,} "
         f"({flooded_n/max(total,1)*100:.2f}%) -> {a.out}", 1.0)


if __name__ == "__main__":
    main()
