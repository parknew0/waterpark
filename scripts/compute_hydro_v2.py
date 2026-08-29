#!/usr/bin/env python3
"""Sink-filled flow routing, and the depression depth that filling reveals.

The first attempt left depressions unfilled on the reasoning that a sink is
where water pools, which is what we want to predict. That reasoning inverts
what D8 routing does: with sinks left in, every one of them -- including DEM
noise a few centimetres deep -- terminates the flow path. Accumulation came out
at a median of two cells and half the country never received water from
anywhere, so the feature measured nothing and duly failed its ablation.

Filling gives both halves of the physics instead of neither:

  flow_acc   how much land drains through here (on the filled surface)
  sink_depth how deep the hollow is that filling had to erase -- the storage
             that has to be exceeded before water leaves, which is the closest
             thing in the terrain to "can it pond here, and how much"

Grayscale reconstruction by erosion is the standard way to fill: seed the
surface at maximum everywhere except the border, then let it relax down to the
DEM. Where it settles above the ground, that gap is the depression.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
from skimage.morphology import reconstruction

ROOT = Path(__file__).resolve().parents[1]
NB = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]


def fill_sinks(dem: np.ndarray) -> np.ndarray:
    seed = np.full(dem.shape, dem.max(), dtype="float32")
    seed[0, :] = dem[0, :]; seed[-1, :] = dem[-1, :]
    seed[:, 0] = dem[:, 0]; seed[:, -1] = dem[:, -1]
    return reconstruction(seed, dem, method="erosion").astype("float32")


def fill_epsilon(dem: np.ndarray, eps: float = 1e-3) -> np.ndarray:
    """Priority-flood, raising each cell a hair above the one it drains to.

    A plain fill turns every depression into a perfectly flat lid, and D8 has
    no lower neighbour to hand water to on a flat, so routing dies exactly
    where filling was supposed to help. Giving each filled cell a millimetre
    more than its outlet leaves a monotonic path out of every hollow.
    """
    import heapq
    rows, cols = dem.shape
    out = np.full(dem.shape, np.inf, dtype="float32")
    done = np.zeros(dem.shape, dtype=bool)
    heap = []
    for r in range(rows):
        for c in (0, cols - 1):
            if np.isfinite(dem[r, c]):
                heapq.heappush(heap, (float(dem[r, c]), r, c)); out[r, c] = dem[r, c]; done[r, c] = True
    for c in range(cols):
        for r in (0, rows - 1):
            if np.isfinite(dem[r, c]) and not done[r, c]:
                heapq.heappush(heap, (float(dem[r, c]), r, c)); out[r, c] = dem[r, c]; done[r, c] = True
    while heap:
        h, r, c = heapq.heappop(heap)
        for dr, dc in NB:
            nr, nc = r + dr, c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols or done[nr, nc]:
                continue
            v = dem[nr, nc]
            if not np.isfinite(v):
                continue
            nv = v if v > h + eps else h + eps
            out[nr, nc] = nv; done[nr, nc] = True
            heapq.heappush(heap, (float(nv), nr, nc))
    return out


def flow_accumulation(dem: np.ndarray) -> np.ndarray:
    """D8: every cell hands its water to its steepest lower neighbour."""
    rows, cols = dem.shape
    acc = np.ones(dem.shape, dtype="float32")
    order = np.argsort(dem, axis=None)[::-1]          # 높은 곳부터
    rr, cc = np.unravel_index(order, dem.shape)
    dist = np.array([np.sqrt(2), 1, np.sqrt(2), 1, 1, np.sqrt(2), 1, np.sqrt(2)],
                    dtype="float32")
    for i in range(len(rr)):
        r, c = rr[i], cc[i]
        h = dem[r, c]
        if not np.isfinite(h):
            continue
        best, br, bc = 0.0, -1, -1
        for k, (dr, dc) in enumerate(NB):
            nr, nc = r + dr, c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            nh = dem[nr, nc]
            if not np.isfinite(nh):
                continue
            drop = (h - nh) / dist[k]
            if drop > best:
                best, br, bc = drop, nr, nc
        if br >= 0:
            acc[br, bc] += acc[r, c]
    return acc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data/interim/hydro/grid_hydro_v2.npz")
    a = ap.parse_args()

    base = np.load(ROOT / "data/interim/hydro/grid_hydro_full.npz")
    dem = base["elevation"].astype("float32")
    slope = base["slope_deg"].astype("float32")
    land = np.isfinite(dem)
    work = np.where(land, dem, np.nanmax(dem[land])).astype("float32")

    print("[메우기] 시작", flush=True)
    filled = fill_sinks(work)
    sink = np.clip(filled - work, 0, None)
    routed = fill_epsilon(work)
    print(f"  웅덩이가 있는 땅 {(sink[land] > 0.01).mean()*100:.1f}%  "
          f"그 깊이 중앙 {np.median(sink[land][sink[land] > 0.01]):.2f} m", flush=True)

    print("[물길] 집수면적 계산", flush=True)
    acc = flow_accumulation(np.where(land, routed, np.nan))
    print(f"  집수면적 중앙 {np.median(acc[land]):.0f}칸  최대 {acc[land].max():,.0f}칸",
          flush=True)

    twi = np.log((acc * 100.0 * 100.0)
                 / np.maximum(np.tan(np.radians(np.maximum(slope, 0.05))), 1e-4))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, flow_acc=acc.astype("float32"),
                        sink_depth=sink.astype("float32"), twi=twi.astype("float32"))
    print(f"[결과] -> {a.out}")


if __name__ == "__main__":
    main()
