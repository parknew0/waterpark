#!/usr/bin/env python3
"""2023 년 침수 라벨을 기존 라벨 묶음에 더한다.

침수흔적도 본 자료는 2022 년에서 끊긴다. 그런데 2025 년에 따로 올라온 심선·위선
자료에 2023 년이 들어 있었다. 위선에는 침수 시작 시각(SAT_TM)과 원인까지 있어,
지금까지 따로 만들어 두던 flood_hours 를 추정이 아니라 자료에서 가져올 수 있다.

폴리곤이 아니라 측선의 점이므로 한 사건의 칸 수가 적다. 링 센서스는 점 둘레에
2 km 고리를 두르므로 점이면 충분하지만, 라벨이 폴리곤보다 성기다는 것은
기록해 둔다 -- 2023 년 사건의 침수 칸은 폴리곤 사건보다 훨씬 적게 잡힌다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
LAB = ROOT / "data/interim/flood-labels"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", default="2023")
    ap.add_argument("--out", type=Path, default=LAB / "flood_cells30_plus.npz")
    ap.add_argument("--hours-out", type=Path,
                    default=ROOT / "config/radar/flood_hours_plus.json")
    a = ap.parse_args()

    w = pd.DataFrame(json.loads((ROOT / "data/raw/flood-trace/flood_trace_wiseon.json")
                                .read_text(encoding="utf-8")))
    s = pd.DataFrame(json.loads((ROOT / "data/raw/flood-trace/flood_trace_shim.json")
                                .read_text(encoding="utf-8")))
    w["day"] = w.SAT_DATE.astype(str)
    w = w[w.FLUD_YEAR == a.year]
    # 심선에는 날짜가 없다. 같은 해 같은 읍면동에 위선이 있으면 그 날짜를 빌린다.
    day_of = w.groupby("EMD_CD").day.agg(lambda x: x.mode().iat[0])
    s = s[s.FLUD_YEAR == a.year].copy()
    s["day"] = s.EMD_CD.map(day_of)
    pts = pd.concat([w[["X", "Y", "day"]], s.dropna(subset=["day"])[["X", "Y", "day"]]])
    print(f"{a.year}년 점 {len(pts):,}개 (위선 {len(w):,} + 심선 {len(s.dropna(subset=['day'])):,})")

    meta = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    t = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:5179", always_xy=True)
    x, y = t.transform(pts.X.to_numpy(dtype="float64"), pts.Y.to_numpy(dtype="float64"))
    rr = ((meta["origin_y_top"] - y) // cell).astype(np.int64)
    cc = ((x - meta["origin_x"]) // cell).astype(np.int64)
    ok = (rr >= 0) & (rr < R) & (cc >= 0) & (cc < C)
    pts = pts[ok].copy()
    pts["key"] = rr[ok] * C + cc[ok]

    old = np.load(LAB / "flood_cells30.npz")
    out = {k: old[k] for k in old.files}
    hours = json.loads((ROOT / "config/radar/flood_hours.json").read_text(encoding="utf-8"))
    added = 0
    for day, grp in pts.groupby("day"):
        k = np.unique(grp.key.to_numpy())
        name = "e" + str(day)
        if name in out:                      # 이미 있으면 합친다
            k = np.unique(np.r_[out[name], k])
        out[name] = k
        added += 1
        tm = w[w.day == day].SAT_TM.dropna()
        if len(tm):
            hours[str(day)] = int(str(tm.iat[0])[:2])
    np.savez_compressed(a.out, **out)
    a.hours_out.write_text(json.dumps(hours, ensure_ascii=False), encoding="utf-8")
    ev = [k[1:] for k in out if k.startswith("e")]
    print(f"사건 {len(old.files)-2} -> {len(ev)}개  ({added}일 추가/갱신)")
    print(f"  침수 칸 {sum(len(out['e'+e]) for e in ev):,}개")
    print(f"  -> {a.out}")
    print(f"  -> {a.hours_out}  (침수 시각을 자료에서 가져왔다)")


if __name__ == "__main__":
    main()
