#!/usr/bin/env python3
"""타일로 나눈 물길 추적과 전국 한 번에 한 것을 실제로 대조한다.

타일 분할은 90 km 넘게 흘러오는 물길을 끊는다. 그런 물은 하천을 타고 오는
것이고 하천범람 라벨은 이미 제외했으니 타당한 근사라고 판단했지만, 판단은
판단이고 차이가 얼마인지는 재봐야 안다. 메모리도 마찬가지다 -- 못 한다고
말했던 근거가 옛 구현 기준이었으므로 실제로 들어가는지 확인한다.
"""
from __future__ import annotations
import json, resource, sys, time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_grid30 as g30

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/interim/grid30"


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 3)


def main() -> None:
    el = np.load(OUT / "elevation.npy")
    work = np.where(np.isfinite(el) & (el > 0), el, np.nan).astype("float32")
    del el
    print(f"[전국] {work.shape} = {work.size/1e6:.0f}M 칸  현재 메모리 {rss_gb():.1f}GB",
          flush=True)

    t = time.time()
    routed = g30.fill_and_route(work, np.float32(1e-3))
    print(f"[메우기] {time.time()-t:.0f}초  최대 메모리 {rss_gb():.1f}GB", flush=True)

    t = time.time()
    acc = g30.accumulate(routed)
    print(f"[물길] {time.time()-t:.0f}초  최대 메모리 {rss_gb():.1f}GB", flush=True)

    land = np.isfinite(work)
    sink = np.clip(np.where(np.isfinite(routed), routed, 0)
                   - np.where(land, work, 0), 0, None)
    np.save(OUT / "flow_acc_full.npy", acc)
    np.save(OUT / "sink_depth_full.npy", sink.astype("float32"))

    tiled = np.load(OUT / "flow_acc.npy", mmap_mode="r")
    ts = np.load(OUT / "sink_depth.npy", mmap_mode="r")
    m = land
    a_t = np.asarray(tiled)[m]
    a_f = acc[m]
    print(f"\n=== 집수면적 ===")
    print(f"  타일   중앙 {np.median(a_t):8.0f}칸  최대 {a_t.max():12,.0f}칸")
    print(f"  전국   중앙 {np.median(a_f):8.0f}칸  최대 {a_f.max():12,.0f}칸")
    same = (a_t == a_f).mean() * 100
    print(f"  값이 같은 칸 {same:.1f}%")
    for q in (50, 90, 99, 99.9):
        print(f"    상위 {100-q:4.1f}% 지점: 타일 {np.percentile(a_t,q):10,.0f}"
              f"   전국 {np.percentile(a_f,q):10,.0f}")
    s_t = np.asarray(ts)[m]; s_f = sink[m]
    print(f"\n=== 웅덩이 깊이 ===")
    print(f"  타일 {(s_t>0.01).mean()*100:.1f}%가 웅덩이, 깊이 중앙 {np.median(s_t[s_t>0.01]):.2f}m")
    print(f"  전국 {(s_f>0.01).mean()*100:.1f}%가 웅덩이, 깊이 중앙 {np.median(s_f[s_f>0.01]):.2f}m")
    print(f"  깊이 최대 차이 {np.abs(s_t-s_f).max():.2f}m")
    print(f"\n최대 메모리 {rss_gb():.1f}GB")


if __name__ == "__main__":
    main()
