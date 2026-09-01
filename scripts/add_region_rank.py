#!/usr/bin/env python3
"""지형 변수를 \033[1m그 지역 안에서의 순위\033[0m 로 바꿔 덧붙인다.

시도를 통째로 빼고 재 봤더니 상위 5% 포착이 50.4% 에서 27.0% 로 떨어졌다. 안 가본
지역이 안 본 폭풍보다 훨씬 어렵다.

원인의 하나가 드러났다. 시도마다 표고 폭이 105 m 에서 511 m 까지 다섯 배 차이다.
"해발 50 m" 가 전북에서는 낮은 땅이고 세종에서는 높은 땅이다. 그런데 모델이 쓰는
21 개 열에는 \033[1m위치 정보가 하나도 없어서\033[0m 그 차이를 알 길이 없다.

그래서 "이 칸은 자기 시군구 안에서 아래쪽 몇 % 인가" 를 더한다. 지역이 달라도 뜻이
같은 값이라 안 가본 지역으로 옮겨간다.

위치를 좌표로 넣지 않는 이유: 좌표를 주면 모델이 지역을 외운다. 외운 것은 안 가본
지역에서 쓸모가 없고 오히려 해가 된다. 순위는 외울 것이 없다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
RANKED = ["elevation", "rel_500m", "sink_depth", "slope_deg", "flow_acc",
          "impervious", "dist_stream", "sewer_density"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_146.csv")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_rank.csv")
    ap.add_argument("--chunk", type=int, default=3_000_000)
    a = ap.parse_args()

    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    sid = np.load(G30 / "sgg_id.npy", mmap_mode="r")
    to5179 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    # 1) 시군구를 붙여가며 각 변수의 값을 모은다 (순위 기준을 만들기 위해)
    print("1단계: 시군구별 분포를 모은다", flush=True)
    pools: dict[tuple, list] = {}
    for n, ch in enumerate(pd.read_csv(a.table, usecols=["lon", "lat", *RANKED],
                                       chunksize=a.chunk)):
        x, y = to5179.transform(ch.lon.to_numpy(), ch.lat.to_numpy())
        r = ((g["origin_y_top"] - y) // g["cell_m"]).astype(np.int64)
        c = ((x - g["origin_x"]) // g["cell_m"]).astype(np.int64)
        ok = (r >= 0) & (r < g["rows"]) & (c >= 0) & (c < g["cols"])
        s = np.zeros(len(ch), dtype=np.int32)
        s[ok] = np.asarray(sid)[r[ok], c[ok]]
        ch = ch.assign(sgg=s)
        for col in RANKED:
            for k, part in ch.groupby("sgg")[col]:
                if k == 0:
                    continue
                # 분위 경계만 있으면 되므로 표본으로 충분하다. 전부 쥐면 메모리가 터진다.
                v = part.to_numpy(dtype="float32")
                v = v[np.isfinite(v)]
                if len(v) > 4000:
                    v = np.random.default_rng(0).choice(v, 4000, replace=False)
                pools.setdefault((col, int(k)), []).append(v)
        print(f"  덩어리 {n+1} 처리", flush=True)
    # 시군구에 따라 그 변수가 통째로 비어 있을 수 있다 (하수관 밀도 등).
    # 빈 것을 quantile 에 넣으면 터진다. 값이 충분한 것만 남긴다.
    edges = {}
    for k, v in pools.items():
        arr = np.concatenate(v) if v else np.empty(0, "float32")
        if len(arr) >= 20:
            edges[k] = np.quantile(arr, np.linspace(0, 1, 101))
    print(f"  시군구 x 변수 = {len(edges):,}개 기준 완성", flush=True)
    del pools

    # 2) 다시 훑으며 순위(0~1)를 붙인다
    print("2단계: 순위를 붙인다", flush=True)
    if a.out.exists():
        a.out.unlink()
    total = 0
    for ch in pd.read_csv(a.table, chunksize=a.chunk, dtype={"event": str}):
        x, y = to5179.transform(ch.lon.to_numpy(), ch.lat.to_numpy())
        r = ((g["origin_y_top"] - y) // g["cell_m"]).astype(np.int64)
        c = ((x - g["origin_x"]) // g["cell_m"]).astype(np.int64)
        ok = (r >= 0) & (r < g["rows"]) & (c >= 0) & (c < g["cols"])
        s = np.zeros(len(ch), dtype=np.int32)
        s[ok] = np.asarray(sid)[r[ok], c[ok]]
        for col in RANKED:
            out = np.full(len(ch), np.nan, dtype="float32")
            v = ch[col].to_numpy(dtype="float32")
            for k in np.unique(s):
                if k == 0 or (col, int(k)) not in edges:
                    continue
                m = s == k
                out[m] = np.searchsorted(edges[(col, int(k))], v[m]) / 100.0
            ch[f"q_{col}"] = np.clip(out, 0, 1)
        ch.to_csv(a.out, mode="a", header=not a.out.exists(), index=False)
        total += len(ch)
        print(f"  {total:,}칸", flush=True)
    print(f"[결과] {total:,}칸, 순위 열 {len(RANKED)}개 추가 -> {a.out}")


if __name__ == "__main__":
    main()
