#!/usr/bin/env python3
"""The whole feature stack at 30 m instead of 100 m.

A 100 m cell is a football pitch, and it holds a road, a building, a yard and a
car park at once. Averaging them into one number erases exactly the things that
flood: the underpass five metres below the road beside it, the alley that sits
lower than its block. The DEM underneath was always 30 m -- the coarser grid
was our choice, not the data's -- so this rebuilds every layer at the source
resolution.

Contributing area is computed on overlapping tiles rather than across the whole
country, and that is a physical choice as much as a practical one: water
arriving from tens of kilometres upstream arrives down a river, which is
fluvial flooding, and those labels were removed. What matters here is the land
that drains to a cell from close by.

Progress is written to status.json so a second terminal can watch.
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/interim/grid30"
CELL = 30.0
STATUS = OUT / "status.json"


def note(step: str, msg: str, frac: float | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cur = {}
    if STATUS.exists():
        try:
            cur = json.loads(STATUS.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    cur["step"] = step
    cur["message"] = msg
    cur["updated"] = time.strftime("%H:%M:%S")
    if frac is not None:
        cur["percent"] = round(frac * 100, 1)
    hist = cur.get("history", [])
    if not hist or hist[-1] != f"{step}: {msg}":
        hist.append(f"{time.strftime('%H:%M')} {step}: {msg}")
    cur["history"] = hist[-30:]
    STATUS.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{step}] {msg}", flush=True)


def meta30() -> dict:
    m = json.loads((ROOT / "data/processed/serving-bundle/grid_meta.json")
                   .read_text(encoding="utf-8"))["grid"]
    # 100/30 is not a whole number: rounding the factor to 3 and then using a
    # 30 m cell would quietly shrink the country by a tenth. Cover the same
    # ground instead, and let the cell counts fall where they fall.
    import math
    return {"cell_m": CELL, "epsg": m["epsg"], "origin_x": m["origin_x"],
            "origin_y_top": m["origin_y_top"],
            "rows": math.ceil(m["rows"] * m["cell_m"] / CELL),
            "cols": math.ceil(m["cols"] * m["cell_m"] / CELL),
            "covers_m": [m["rows"] * m["cell_m"], m["cols"] * m["cell_m"]]}


def step_dem(g: dict) -> None:
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.merge import merge
    import glob
    tiles = sorted(glob.glob(str(ROOT / "data/raw/dem/*.tif")))
    note("DEM", f"타일 {len(tiles)}개 병합 준비", 0.0)
    srcs = [rasterio.open(t) for t in tiles]
    dst = np.full((g["rows"], g["cols"]), np.nan, dtype="float32")
    transform = rasterio.transform.from_origin(
        g["origin_x"], g["origin_y_top"], CELL, CELL)
    band, src_transform = merge(srcs, resampling=Resampling.bilinear)
    note("DEM", "재투영 중 (EPSG:4326 -> 5179, 30 m)", 0.4)
    reproject(source=band[0], destination=dst,
              src_transform=src_transform, src_crs=srcs[0].crs,
              dst_transform=transform, dst_crs=f"EPSG:{g['epsg']}",
              resampling=Resampling.bilinear, src_nodata=srcs[0].nodata,
              dst_nodata=np.nan)
    for s in srcs:
        s.close()
    np.save(OUT / "elevation.npy", dst)
    ok = np.isfinite(dst) & (dst > 0)
    note("DEM", f"완료 — 육지 {ok.sum():,}칸 ({ok.mean()*100:.1f}%), "
                f"고도 중앙 {np.nanmedian(dst[ok]):.0f} m", 1.0)



def step_terrain(g: dict) -> None:
    """주변보다 얼마나 높은가, 그리고 경사. 100 m판과 같은 정의를 쓴다."""
    from scipy.ndimage import minimum_filter, uniform_filter
    el = np.load(OUT / "elevation.npy")
    land = np.isfinite(el) & (el > 0)
    work = np.where(land, el, np.inf).astype("float32")
    for i, radius in enumerate((200, 500, 1000, 2000)):
        k = int(round(radius / CELL)) * 2 + 1
        note("지형", f"주변 {radius} m 최저점 대비 높이 계산 (창 {k}칸)",
             i / 6)
        low = minimum_filter(work, size=k, mode="nearest")
        rel = np.where(land, el - low, np.nan).astype("float32")
        np.save(OUT / f"rel_{radius}m.npy", rel)
        del low, rel
    note("지형", "경사 계산", 4 / 6)
    flat = np.where(land, el, 0.0).astype("float32")
    gy, gx = np.gradient(flat, CELL)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")
    np.save(OUT / "slope_deg.npy", np.where(land, slope, np.nan))
    note("지형", f"완료 — 경사 중앙 {np.nanmedian(slope[land]):.1f}도", 1.0)


from numba import njit

@njit(cache=True)
def fill_and_route(dem, eps):
    rows, cols = dem.shape
    out = np.full(dem.shape, np.inf, dtype=np.float32)
    done = np.zeros(dem.shape, dtype=np.bool_)
    n = rows * cols
    hv = np.empty(n, dtype=np.float32)
    hi = np.empty(n, dtype=np.int32)
    size = 0
    for r in range(rows):
        for c in range(cols):
            if r == 0 or c == 0 or r == rows - 1 or c == cols - 1:
                v = dem[r, c]
                if not np.isnan(v):
                    out[r, c] = v
                    done[r, c] = True
                    hv[size] = v; hi[size] = r * cols + c; size += 1
                    j = size - 1
                    while j > 0:
                        par = (j - 1) // 2
                        if hv[par] <= hv[j]:
                            break
                        hv[par], hv[j] = hv[j], hv[par]
                        hi[par], hi[j] = hi[j], hi[par]
                        j = par
    dr = np.array([-1, -1, -1, 0, 0, 1, 1, 1])
    dc = np.array([-1, 0, 1, -1, 1, -1, 0, 1])
    while size > 0:
        h = hv[0]; idx = hi[0]
        size -= 1
        hv[0] = hv[size]; hi[0] = hi[size]
        j = 0
        while True:
            l = 2 * j + 1; rr2 = l + 1; sm = j
            if l < size and hv[l] < hv[sm]: sm = l
            if rr2 < size and hv[rr2] < hv[sm]: sm = rr2
            if sm == j: break
            hv[sm], hv[j] = hv[j], hv[sm]
            hi[sm], hi[j] = hi[j], hi[sm]
            j = sm
        r = idx // cols; c = idx % cols
        for k in range(8):
            nr = r + dr[k]; nc = c + dc[k]
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols or done[nr, nc]:
                continue
            v = dem[nr, nc]
            if np.isnan(v):
                continue
            nv = v if v > h + eps else h + eps
            out[nr, nc] = nv; done[nr, nc] = True
            hv[size] = nv; hi[size] = nr * cols + nc; size += 1
            j = size - 1
            while j > 0:
                par = (j - 1) // 2
                if hv[par] <= hv[j]: break
                hv[par], hv[j] = hv[j], hv[par]
                hi[par], hi[j] = hi[j], hi[par]
                j = par
    return out

@njit(cache=True)
def accumulate(dem):
    rows, cols = dem.shape
    acc = np.ones(dem.shape, dtype=np.float32)
    order = np.argsort(dem.ravel())[::-1]
    dr = np.array([-1, -1, -1, 0, 0, 1, 1, 1])
    dc = np.array([-1, 0, 1, -1, 1, -1, 0, 1])
    dist = np.array([1.4142, 1.0, 1.4142, 1.0, 1.0, 1.4142, 1.0, 1.4142],
                    dtype=np.float32)
    for t in range(order.size):
        idx = order[t]
        r = idx // cols; c = idx % cols
        h = dem[r, c]
        if np.isnan(h) or np.isinf(h):
            continue
        best = 0.0; br = -1; bc = -1
        for k in range(8):
            nr = r + dr[k]; nc = c + dc[k]
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            nh = dem[nr, nc]
            if np.isnan(nh) or np.isinf(nh):
                continue
            drop = (h - nh) / dist[k]
            if drop > best:
                best = drop; br = nr; bc = nc
        if br >= 0:
            acc[br, bc] += acc[r, c]
    return acc


def step_hydro(g: dict, tile: int = 3000, halo: int = 200) -> None:
    """겹치는 타일 위에서 메우기와 물길 추적.

    타일 하나가 90 km, 겹침이 6 km다. 그보다 먼 데서 오는 물은 하천을 타고
    오는 것이고, 그 라벨은 이미 제외했다."""
    el = np.load(OUT / "elevation.npy")
    R, C = el.shape
    acc_all = np.ones((R, C), dtype="float32")
    sink_all = np.zeros((R, C), dtype="float32")
    steps = ((R + tile - 1) // tile) * ((C + tile - 1) // tile)
    n = 0
    for r0 in range(0, R, tile):
        for c0 in range(0, C, tile):
            r1, c1 = min(r0 + tile, R), min(c0 + tile, C)
            a0, b0 = max(0, r0 - halo), max(0, c0 - halo)
            a1, b1 = min(R, r1 + halo), min(C, c1 + halo)
            sub = el[a0:a1, b0:b1].astype("float32")
            if not np.isfinite(sub).any():
                n += 1
                continue
            hi_val = np.nanmax(sub)
            work = np.where(np.isfinite(sub) & (sub > 0), sub, np.nan).astype("float32")
            if not np.isfinite(work).any():
                n += 1
                continue
            routed = fill_and_route(work, np.float32(1e-3))
            acc = accumulate(routed)
            sink = np.clip(np.where(np.isfinite(routed), routed, 0)
                           - np.where(np.isfinite(work), work, 0), 0, None)
            acc_all[r0:r1, c0:c1] = acc[r0 - a0:r1 - a0, c0 - b0:c1 - b0]
            sink_all[r0:r1, c0:c1] = sink[r0 - a0:r1 - a0, c0 - b0:c1 - b0]
            n += 1
            note("수문", f"타일 {n}/{steps}", n / steps)
    np.save(OUT / "flow_acc.npy", acc_all)
    np.save(OUT / "sink_depth.npy", sink_all)
    land = np.isfinite(el) & (el > 0)
    note("수문", f"완료 — 집수 중앙 {np.median(acc_all[land]):.0f}칸 "
                 f"최대 {acc_all[land].max():,.0f}칸, "
                 f"웅덩이 {(sink_all[land] > 0.01).mean()*100:.1f}%", 1.0)



def step_landuse(g: dict) -> None:
    """건물은 원본에서 30 m로 다시 집계하고, 토지피복은 100 m판을 올려 쓴다.

    건물 도형은 로컬에 있으니 30 m로 다시 세면 도로와 건물이 갈린다.
    토지피복은 10 m 원본을 이미 버려서 다시 받아야 하는데, 그건 40분짜리
    별도 작업이라 지금은 100 m 값을 그대로 확대해 쓴다 -- 이 층만 거칠다는
    것을 알고 쓰는 것과 모르고 쓰는 것은 다르다.
    """
    import glob, sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bi", ROOT / "scripts/build_impervious_grid.py")
    bi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bi)

    rows, cols = g["rows"], g["cols"]
    count = np.zeros((rows, cols), dtype="int32")
    built = np.zeros((rows, cols), dtype="float32")
    shps = sorted(glob.glob(str(ROOT / "data/raw/vworld-buildings/national/*/*.shp")))
    for i, shp in enumerate(shps):
        cx, cy, area = bi.read_shp(Path(shp))
        x, y = bi.TO_5179(cx, cy)
        r = ((g["origin_y_top"] - y) // CELL).astype(np.int64)
        c = ((x - g["origin_x"]) // CELL).astype(np.int64)
        keep = ((r >= 0) & (r < rows) & (c >= 0) & (c < cols)
                & np.isfinite(area) & (area < CELL * CELL * 4))
        np.add.at(count, (r[keep], c[keep]), 1)
        np.add.at(built, (r[keep], c[keep]), area[keep].astype("float32"))
        note("토지이용", f"건물 {i+1}/{len(shps)} 시군 처리", (i + 1) / (len(shps) + 2))
    np.save(OUT / "built_ratio.npy", np.clip(built / (CELL * CELL), 0, 1))
    np.save(OUT / "built_count.npy", count)

    note("토지이용", "토지피복 100 m판을 30 m로 확대", (len(shps) + 1) / (len(shps) + 2))
    lc = np.load(ROOT / "data/interim/hydro/grid_landcover_5179.npz")
    m100 = json.loads((ROOT / "data/processed/serving-bundle/grid_meta.json")
                      .read_text(encoding="utf-8"))["grid"]
    ri = np.minimum(((np.arange(rows) * CELL) // m100["cell_m"]).astype(int),
                    m100["rows"] - 1)
    ci = np.minimum(((np.arange(cols) * CELL) // m100["cell_m"]).astype(int),
                    m100["cols"] - 1)
    for name in ("impervious", "water"):
        np.save(OUT / f"{name}.npy", lc[name][np.ix_(ri, ci)].astype("float32"))
    b = np.load(OUT / "built_ratio.npy")
    note("토지이용", f"완료 — 건물 있는 칸 {(b > 0).mean()*100:.1f}%, "
                     f"그 칸 건폐율 중앙 {np.median(b[b > 0])*100:.1f}%", 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step", default="all")
    a = ap.parse_args()
    g = meta30()
    (OUT / "grid_meta30.json").write_text(json.dumps({"grid": g}, indent=2),
                                          encoding="utf-8")
    note("시작", f"30 m 격자 {g['rows']:,} x {g['cols']:,} = "
                 f"{g['rows']*g['cols']/1e6:.0f}M 칸", 0.0)
    if a.step in ("all", "dem"):
        step_dem(g)
    if a.step in ("all", "terrain"):
        step_terrain(g)
    if a.step in ("all", "hydro"):
        step_hydro(g)
    if a.step in ("all", "landuse"):
        step_landuse(g)


if __name__ == "__main__":
    main()
