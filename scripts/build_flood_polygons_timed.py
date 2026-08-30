#!/usr/bin/env python3
"""침수 칸을 시각과 함께 칠한다.

지금까지는 사건 하나에 시각 하나를 썼다. 그런데 흔적 자료는 폴리곤마다
시작 시각을 담고 있고, 실제로 다르다 -- 2022-08-08은 22개 시각에 걸쳐
있다. 그 차이를 쓰면 사건 한 개가 여러 시점이 된다.

시점 T에서 어떤 칸의 답은 "T까지 잠겼는가"이고, 입력은 T까지 내린 비다.
같은 땅이 32 mm에서는 안 잠기고 58 mm에서는 잠겼다는 대비가 그대로 학습
자료가 되며, 이것이 우리가 알고 싶은 임계값 그 자체다.

앞선 시도는 침수한 칸에만 강수를 줄인 사본을 붙였는데, 그러면 모델은
임계값이 아니라 "침수 칸의 절반은 음성"이라는 모순을 배운다. 여기서는
모든 칸에 대해 그 시점의 답을 만든다.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

import numpy as np
import pyproj
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parents[1]
RIVER = re.compile("하천|범람|제방|월류")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trace", type=Path,
                    default=ROOT / "data/raw/flood-trace/korea_flood_2002_2022.geojson")
    ap.add_argument("--grid", type=Path, default=ROOT / "data/interim/grid30")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data/interim/flood-labels/flood_cells30_timed.npz")
    a = ap.parse_args()

    meta = json.loads((a.grid / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    T = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    feats = json.loads(a.trace.read_text(encoding="utf-8"))["features"]
    print(f"흔적 {len(feats):,}건", flush=True)

    # (사건, 시각) -> 칸 집합
    out: dict[str, dict[int, set]] = {}
    n_river = n_notime = 0
    for i, f in enumerate(feats):
        p = f["properties"]
        m = re.match(r"^(20\d{2})[-/.]?(\d{2})[-/.]?(\d{2})",
                     str(p.get("fldn_bgng_ymd", "")))
        if not m:
            continue
        if RIVER.search(str(p.get("fldn_cs_dtl_nm") or "")):
            n_river += 1
            continue
        tm = re.match(r"^(\d{1,2})", str(p.get("fldn_bgng_tm", "")).strip())
        if not tm:
            n_notime += 1
            continue
        ev = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        hour = int(tm.group(1))
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        slot = out.setdefault(ev, {}).setdefault(hour, set())
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
                slot.add(int((r0 + r1) // 2) * C + int((c0 + c1) // 2))
            else:
                slot.update(((rr + r0).astype(np.int64) * C + (cc + c0)).tolist())
        if (i + 1) % 5000 == 0:
            print(f"  {i+1:,}/{len(feats):,}", flush=True)

    payload = {"rows": R, "cols": C}
    n_cell = 0
    for ev, byhour in out.items():
        for hour, cells in byhour.items():
            payload[f"e{ev}_h{hour:02d}"] = np.array(sorted(cells), dtype=np.int64)
            n_cell += len(cells)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, **payload)
    slots = sum(len(v) for v in out.values())
    print(f"\n[결과] 사건 {len(out)}개, (사건,시각) 조합 {slots}개, 침수 칸 {n_cell:,}")
    print(f"  하천 범람 제외 {n_river:,}, 시각 없음 제외 {n_notime:,}")
    big = sorted(out.items(), key=lambda kv: -sum(len(s) for s in kv[1].values()))[:5]
    for ev, byhour in big:
        print(f"  {ev}: 시각 {len(byhour)}개, 칸 {sum(len(s) for s in byhour.values()):,}")
    print(f"  -> {a.out}")


if __name__ == "__main__":
    main()
