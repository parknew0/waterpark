#!/usr/bin/env python3
"""조사 범위 전수 조사를, 사건이 아니라 (사건, 시각) 단위로.

흔적 자료는 폴리곤마다 침수 시작 시각을 담고 있고 사건 안에서 실제로
다르다. 시점 T마다 "그때까지 잠긴 칸"과 "그때까지 내린 비"를 짝지으면,
같은 땅이 32 mm에서는 안 잠기고 58 mm에서는 잠겼다는 대비가 학습 자료에
직접 들어온다. 사건 27개가 (사건, 시각) 200여 개가 되며, 학습 곡선이
아직 꺾이지 않았으므로 그 자체로 값어치가 있다.

원래 판(build_ring_census30.py)은 사건마다 침수 시각 하나만 쓴다.

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
                    default=ROOT / "data/interim/flood-labels/flood_cells30_timed.npz",
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
        polys = {}
        for k in z.files:
            if not k.startswith("e") or "_h" not in k:
                continue
            ev_k, hh = k[1:].split("_h")
            polys.setdefault(ev_k, {})[int(hh)] = set(z[k].tolist())
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
        if polys is None or ev not in polys:
            continue
        z = np.load(path)
        stamps = z["stamps"]
        spans = z["span_min"].astype("float64")
        grid = z["grid"].astype("float32") / 100.0            # dBZ
        series_all = rate(grid).reshape(len(spans), -1)       # mm/h
        del grid

        # 고리는 사건 전체 침수 기록 기준으로 한 번만 잡는다
        rows = (case.row.to_numpy()[:, None] + dy).ravel()
        cols = (case.col.to_numpy()[:, None] + dx).ravel()
        good = (rows >= 0) & (rows < R) & (cols >= 0) & (cols < C)
        keys = np.unique(rows[good].astype(np.int64) * C + cols[good])
        rr, cc = (keys // C).astype(np.int32), (keys % C).astype(np.int32)

        ftree = cKDTree(np.c_[floods.row.to_numpy(), floods.col.to_numpy()])
        ctree = cKDTree(np.c_[case.row.to_numpy(), case.col.to_numpy()])
        d_any = ftree.query(np.c_[rr, cc], k=1)[0]
        d_own = ctree.query(np.c_[rr, cc], k=1)[0]
        keep_any = d_any > INNER
        el_all = layers["elevation"][rr, cc]
        land_all = np.isfinite(el_all) & (el_all > 0)
        keys_all = rr.astype(np.int64) * C + cc

        # 이 사건에 기록된 시각들. 시각 T의 답은 "T까지 잠겼는가"이고
        # 입력은 T까지 내린 비다. 같은 땅을 여러 강수량에서 보게 된다.
        byhour = polys[ev]
        seen_upto: set = set()
        for hour in sorted(byhour):
            seen_upto |= byhour[hour]
            cut = bett.first_after(stamps, ev, hour)
            if cut is None or cut < 3:
                continue
            totals = bett.accumulate(series_all[:cut], spans[:cut], forward=False)
            flooded = np.fromiter((k in seen_upto for k in keys_all),
                                  bool, len(keys_all))
            keep = (flooded | keep_any) & land_all
            if keep.sum() < 1000 or flooded[keep].sum() < 20:
                continue
            sr, sc = rr[keep], cc[keep]
            x = g["origin_x"] + (sc + 0.5) * cell
            y = g["origin_y_top"] - (sr + 0.5) * cell
            lon, lat = to4326.transform(x, y)
            near = rtree.query(np.c_[lon * 88_000, lat * 111_000], k=1)[1]
            cellidx = ridx[near]
            frame = {"event": f"{ev}_{hour:02d}",
                     "flooded": flooded[keep].astype(np.int8),
                     "lon": lon.astype("float32"), "lat": lat.astype("float32")}
            for nm in LAYERS:
                frame[nm] = np.asarray(layers[nm][sr, sc], dtype="float32")
            for h in WINDOWS:
                frame[f"rain_{h}h"] = totals[h][cellidx].astype("float32")
            df = pd.DataFrame(frame)
            df = df[np.isfinite(df[["elevation", "rel_500m", "rain_24h"]]).all(axis=1)]
            if len(df) < 1000:
                continue
            df.to_csv(a.out, mode="a", header=not a.out.exists(), index=False)
            total += len(df); flooded_n += int(df.flooded.sum())
        note(f"{ev}: 시각 {len(byhour)}개 처리, 누적 {total:,}칸",
             0.05 + 0.9 * (n + 1) / len(files))

    note(f"완료 — {total:,}칸  침수 {flooded_n:,} "
         f"({flooded_n/max(total,1)*100:.2f}%) -> {a.out}", 1.0)


if __name__ == "__main__":
    main()
