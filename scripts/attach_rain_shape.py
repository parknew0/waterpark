#!/usr/bin/env python3
"""비가 '얼마나' 왔는지 말고 '어떻게' 왔는지를 붙인다.

레이더는 5 분 간격 288 단계로 저장돼 있는데 (grids_full 의 series), 우리는 그걸
1·3·6·12·24 시간 합계 다섯 개로 뭉개 쓰고 있었다. 288 개 숫자를 갖고 다섯 개만
쓴 셈이다. 30 분에 쏟아진 60 mm 와 여섯 시간에 고루 온 60 mm 는 배수관 입장에서
완전히 다른 일인데 지금 모델에는 같아 보인다.

침수 시각 이전 6 시간을 보고 다섯 가지를 만든다.

  rain_peak5     가장 센 5 분의 강도 (mm/h)
  rain_peak60    가장 센 한 시간 (mm)
  rain_wet_min   1 mm/h 를 넘긴 시간 (분)
  rain_to_peak   비가 시작해 가장 셀 때까지 걸린 시간 (분)
  rain_burst     6 시간 총량 중 가장 센 한 시간이 차지하는 몫

값은 레이더 격자에서 만들고, 표의 각 칸은 가장 가까운 레이더 칸에서 가져온다.
링 센서스가 강수를 붙이는 방식과 같아야 둘이 어긋나지 않는다.
"""
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
RAD = ROOT / "data/interim/radar"
COLS = ["rain_peak5", "rain_peak60", "rain_wet_min", "rain_to_peak", "rain_burst"]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hours", type=Path, default=ROOT / "config/radar/flood_hours.json")
    ap.add_argument("--window-min", type=int, default=360)
    a = ap.parse_args()

    bett = load("bett", ROOT / "scripts/build_event_training_table.py")
    # dBZ -> mm/h 는 수집기가 쓰는 것과 같은 식이어야 한다 (Z = 200 R^1.6)
    rate_fn = load("crr", ROOT / "scripts/collect_radar_rainfall.py").rain_rate
    anchors = {k: int(v) for k, v in
               json.loads(a.hours.read_text(encoding="utf-8")).items() if v is not None}

    rlon = np.fromfile(RAD / "hsr_lon.bin", dtype="<f4")[1:]
    rlat = np.fromfile(RAD / "hsr_lat.bin", dtype="<f4")[1:]
    ok = np.isfinite(rlon) & np.isfinite(rlat) & (rlon > 120) & (rlon < 133)
    ridx = np.flatnonzero(ok)
    rtree = cKDTree(np.c_[rlon[ok] * 88_000, rlat[ok] * 111_000])

    def shape_for(ev):
        f = RAD / f"grids_full/rain_{ev}_grid.npz"
        if not f.exists() or ev not in anchors:
            return None
        z = np.load(f)
        stamps, spans = z["stamps"], z["span_min"].astype("float64")
        end = len(spans)
        cut = bett.first_after(stamps, ev, anchors[ev])
        if cut is not None and cut >= 2:
            end = cut
        # 침수 시각 앞 window_min 분만 본다
        keep = max(int(a.window_min / max(spans[:end].mean(), 1)), 1)
        s0 = max(end - keep, 0)
        grid = z["grid"][s0:end].astype("float32") / 100.0
        rate = rate_fn(grid).reshape(end - s0, -1)            # mm/h
        del grid
        step = float(np.mean(spans[s0:end])) or 5.0
        per = rate * (step / 60.0)                            # 단계별 mm
        k = max(int(round(60.0 / step)), 1)
        if rate.shape[0] >= k:                                # 한 시간 이동합
            cs = np.cumsum(per, axis=0)
            hour = np.r_[cs[k - 1:k], cs[k:] - cs[:-k]]
        else:
            hour = per.sum(axis=0, keepdims=True)
        tot = per.sum(axis=0)
        peak60 = hour.max(axis=0)
        out = {
            "rain_peak5": rate.max(axis=0),
            "rain_peak60": peak60,
            "rain_wet_min": (rate > 1.0).sum(axis=0) * step,
            "rain_to_peak": rate.argmax(axis=0) * step,
            "rain_burst": np.where(tot > 1.0, peak60 / np.maximum(tot, 1e-6), np.nan),
        }
        return out

    cache, first = {}, True
    if a.out.exists():
        a.out.unlink()
    total = 0
    for ch in pd.read_csv(a.table, chunksize=1_000_000, dtype={"event": str}):
        near = ridx[rtree.query(np.c_[ch.lon.to_numpy() * 88_000,
                                      ch.lat.to_numpy() * 111_000], k=1)[1]]
        for c in COLS:
            ch[c] = np.nan
        for ev in pd.unique(ch.event.to_numpy()):
            if ev not in cache:
                if len(cache) > 3:
                    cache.pop(next(iter(cache)))
                cache[ev] = shape_for(ev)
            sh = cache[ev]
            if sh is None:
                continue
            m = (ch.event.to_numpy() == ev)
            idx = near[m]
            for c in COLS:
                ch.loc[m, c] = sh[c][idx].astype("float32")
        ch.to_csv(a.out, mode="a", header=first, index=False)
        first = False
        total += len(ch)
        got = float(np.isfinite(ch.rain_peak60).mean()) * 100
        print(f"  {total:,}칸  값 붙은 비율 {got:.0f}%", flush=True)
    print(f"[결과] {total:,}칸 -> {a.out}")


if __name__ == "__main__":
    main()
