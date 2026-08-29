#!/usr/bin/env python3
"""침수 흔적을 점이 아니라 면으로 격자에 칠한다.

흔적 조사는 물이 찬 구역을 폴리곤으로 그린다. 넓이가 중앙 8,780 m2이니
30 m 칸으로 열 개쯤 된다. 그런데 지금까지는 그 면을 중심점 하나로 줄여
써왔고, 30 m 격자에서는 그 결과 한 칸만 '잠김'이 되고 지형이 똑같은 옆
아홉 칸이 '안 잠김'으로 학습됐다. 모델에게 모순을 가르친 셈이다.

증거는 침수율에 있다: 30 m에서 0.13%, 100 m에서 1.33%. 열 배 차이는 현실이
아니라 라벨을 만드는 방식이 만든 숫자다.

사건별로 칠한다. 같은 자리가 2020년과 2022년에 각각 잠겼다면 그 두 사건에
대해서만 잠긴 것이지, 비가 오지 않은 해까지 잠긴 것은 아니다.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

import numpy as np
import pyproj
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trace", type=Path,
                    default=ROOT / "data/raw/flood-trace/korea_flood_2002_2022.geojson")
    ap.add_argument("--grid", type=Path, default=ROOT / "data/interim/grid30")
    ap.add_argument("--cause", type=Path,
                    default=ROOT / "data/interim/flood-labels/flood_cause.csv")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data/interim/flood-labels/flood_cells30.npz")
    a = ap.parse_args()

    meta = json.loads((a.grid / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    T = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    feats = json.loads(a.trace.read_text(encoding="utf-8"))["features"]
    print(f"흔적 {len(feats):,}건", flush=True)

    by_event: dict[str, set] = {}
    river_words = re.compile("하천|범람|제방|월류")
    n_poly = n_cell = n_river = 0
    for i, f in enumerate(feats):
        p = f["properties"]
        m = re.match(r"^(20\d{2})[-/.]?(\d{2})[-/.]?(\d{2})", str(p.get("fldn_bgng_ymd", "")))
        if not m:
            continue
        ev = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        # 하천 범람은 상류 유역과 하천 수위가 결정하므로 이 모델의 물리가 아니다
        if river_words.search(str(p.get("fldn_cs_dtl_nm") or "")):
            n_river += 1
            continue
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        cells = by_event.setdefault(ev, set())
        for poly in polys:
            ring = np.asarray(poly[0], dtype="float64")
            if ring.ndim != 2 or len(ring) < 4:
                continue
            x, y = T.transform(ring[:, 0], ring[:, 1])
            c0 = max(int((x.min() - meta["origin_x"]) // cell), 0)
            c1 = min(int((x.max() - meta["origin_x"]) // cell) + 1, C)
            r0 = max(int((meta["origin_y_top"] - y.max()) // cell), 0)
            r1 = min(int((meta["origin_y_top"] - y.min()) // cell) + 1, R)
            if r1 <= r0 or c1 <= c0:
                continue
            gx = meta["origin_x"] + (np.arange(c0, c1) + 0.5) * cell
            gy = meta["origin_y_top"] - (np.arange(r0, r1) + 0.5) * cell
            XX, YY = np.meshgrid(gx, gy)
            inside = MplPath(np.c_[x, y]).contains_points(np.c_[XX.ravel(), YY.ravel()])
            rr, cc = np.nonzero(inside.reshape(r1 - r0, c1 - c0))
            if rr.size == 0:
                # 한 칸보다 작은 폴리곤은 중심점 한 칸으로 남긴다
                cells.add((int((r0 + r1) // 2)) * C + int((c0 + c1) // 2))
            else:
                cells.update(((rr + r0).astype(np.int64) * C + (cc + c0)).tolist())
            n_poly += 1
        if (i + 1) % 5000 == 0:
            print(f"  {i+1:,}/{len(feats):,}  사건 {len(by_event)}  "
                  f"칸 누적 {sum(len(v) for v in by_event.values()):,}", flush=True)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        a.out, rows=R, cols=C,
        **{f"e{ev}": np.array(sorted(v), dtype=np.int64) for ev, v in by_event.items()})
    n_cell = sum(len(v) for v in by_event.values())
    print(f"\n[결과] 사건 {len(by_event)}개, 폴리곤 {n_poly:,}개 -> 침수 칸 {n_cell:,}")
    print(f"  하천 범람으로 제외한 흔적 {n_river:,}건")
    print(f"  점으로 쓸 때보다 {n_cell/max(len(feats)-n_river,1):.1f}배")
    print(f"  -> {a.out}")


if __name__ == "__main__":
    main()
