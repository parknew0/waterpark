#!/usr/bin/env python3
"""수위를 학습표에 붙인다. 시간에 따라 변하는 두 번째 축.

각 칸에서 가까운 관측소를 찾아, 침수 시각 기준으로 세 가지를 만든다.

  wl_level    그 시각의 수위 (m)
  wl_rise_6h  직전 6시간 상승폭 -- 절대 수위는 관측소마다 기준면이 달라
              비교가 안 되지만 상승폭은 비교된다
  wl_dist_km  실제로 값을 가져온 관측소까지 거리. 멀면 그 수위는 이 칸과
              무관하므로 모델이 신뢰도를 스스로 판단할 수 있게 같이 준다

처음 판에는 두 가지 결함이 있었다.

첫째, WAMIS 의 시각은 01~24 이지 00~23 이 아니다. 자정을 00 으로 찾으면 그런
키가 없어 통째로 비었다. 침수 시각이 자정인 사건이 여섯이었고 그중 하나는
침수 칸이 6,512 개였다.

둘째, 관측소를 거리만 보고 골랐다. 2018 년 사건에서 가장 가까운 관측소가
그해에는 아직 없던 곳이라 표본 2,000 칸이 전부 비었다. 관측소는 1,352 곳이지만
2018 년에 보고한 곳은 662 곳뿐이다. 그 시각에 값이 있는 관측소 중에서 골라야
한다.
"""
from __future__ import annotations
import argparse, datetime, json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
WL = ROOT / "data/interim/waterlevel"


def wamis_key(t: datetime.datetime) -> str:
    """WAMIS 는 하루를 01~24 로 적는다. 자정은 전날 24 시다."""
    if t.hour == 0:
        return (t - datetime.timedelta(days=1)).strftime("%Y%m%d") + "24"
    return t.strftime("%Y%m%d%H")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--hours", type=Path, default=ROOT / "config/radar/flood_hours.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--chunk", type=int, default=2_000_000)
    a = ap.parse_args()

    st = pd.DataFrame(json.loads((WL / "stations.json").read_text(encoding="utf-8")))
    st["obscd"] = st.obscd.astype(str)
    hours = {k: int(v) for k, v in
             json.loads(a.hours.read_text(encoding="utf-8")).items() if v is not None}

    cache: dict[str, tuple] = {}

    def lookup(day: str):
        """그 날 그 시각에 값이 있는 관측소만 모아 트리를 세운다."""
        if day in cache:
            return cache[day]
        f = WL / f"wl_{day}.json"
        out = (None, None, None, None)
        if f.exists() and day in hours:
            wl = json.loads(f.read_text(encoding="utf-8"))
            base = datetime.datetime.strptime(day, "%Y%m%d") + \
                datetime.timedelta(hours=hours[day])
            now, back = wamis_key(base), wamis_key(base - datetime.timedelta(hours=6))
            lvl, rise = {}, {}
            for code, ser in wl.items():
                v = ser.get(now)
                if v is None:
                    continue
                lvl[code] = float(v)
                b = ser.get(back)
                if b is not None:
                    rise[code] = float(v) - float(b)
            if lvl:
                sub = st[st.obscd.isin(lvl)]
                out = (cKDTree(np.c_[sub.lon * 88_000, sub.lat * 111_000]),
                       sub.obscd.to_numpy(), lvl, rise)
        cache[day] = out
        return out

    if a.out.exists():
        a.out.unlink()
    total = hit = 0
    for chunk in pd.read_csv(a.table, chunksize=a.chunk, dtype={"event": str}):
        dayv = chunk.event.str.slice(0, 8).to_numpy()
        lon = chunk.lon.to_numpy() * 88_000
        lat = chunk.lat.to_numpy() * 111_000
        d, r6, dist = (np.full(len(chunk), np.nan) for _ in range(3))
        for day in pd.unique(dayv):
            tree, codes, lvl, rise = lookup(day)
            if tree is None:
                continue
            pos = np.flatnonzero(dayv == day)
            dd, ii = tree.query(np.c_[lon[pos], lat[pos]], k=1)
            near = pd.Series(codes[ii])
            d[pos] = near.map(lvl).to_numpy(dtype="float64")
            r6[pos] = near.map(rise).to_numpy(dtype="float64")
            dist[pos] = dd / 1000.0
        chunk["wl_level"] = d
        chunk["wl_rise_6h"] = r6
        chunk["wl_dist_km"] = dist
        chunk.to_csv(a.out, mode="a", header=not a.out.exists(), index=False)
        total += len(chunk); hit += int(np.isfinite(d).sum())
        print(f"  {total:,}칸 처리, 수위 붙은 것 {hit:,} ({hit/total*100:.1f}%)", flush=True)
    print(f"[결과] {total:,}칸 -> {a.out}")


if __name__ == "__main__":
    main()
