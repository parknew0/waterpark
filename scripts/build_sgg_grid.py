#!/usr/bin/env python3
"""시군구 경계를 30 m 격자에 올린다. 기사 채점을 시군구 단위로 하기 위한 것.

기사 자료의 시군구 코드와 우리 경계 파일의 코드는 76% 만 겹친다. 경계 파일이
전남·광주 통합(46xxx/29xxx -> 12xxx) 이후 코드를 쓰기 때문이다. 코드 대신
이름으로 맞추면 93% 가 붙고, 나머지는 경계 파일이 수원시를 장안구·권선구로
쪼개 놓은 경우라 부모 시로 묶으면 된다.

'동구'처럼 여러 시도에 같은 이름이 있으므로 (시도, 시군구) 짝으로 맞춘다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pyproj
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
BND = ROOT / "data/interim/drainage/sgg_boundaries.json"
# 기사 자료의 시도 표기 -> 경계 파일 full_nm 앞부분. 통합으로 이름이 바뀐 곳은
# 옛 이름 둘이 새 이름 하나를 가리킨다.
SIDO_ALIAS = {"전라남도": "전남광주통합특별시", "광주광역시": "전남광주통합특별시",
              "강원도": "강원특별자치도", "전라북도": "전북특별자치도",
              "제주도": "제주특별자치도", "세종시": "세종특별자치시"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=G30 / "sgg_id.npy")
    ap.add_argument("--table", type=Path, default=G30 / "sgg_index.json")
    a = ap.parse_args()

    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = g["rows"], g["cols"], g["cell_m"]
    ox, oyt = g["origin_x"], g["origin_y_top"]
    to5179 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    feats = json.loads(BND.read_text(encoding="utf-8"))
    # 시군구 하나가 여러 구로 쪼개져 있으면 부모 시로 묶는다
    groups: dict[tuple, list] = {}
    for f in feats:
        p = f["properties"]
        parts = p.get("full_nm", "").split()
        sido = parts[0] if parts else ""
        name = parts[-1] if parts else ""
        parent = next((x for x in parts[1:-1] if x.endswith("시")), None)
        groups.setdefault((sido, parent or name), []).append(f)
        if parent:                       # 구 단위로도 찾을 수 있게 둘 다 넣는다
            groups.setdefault((sido, name), []).append(f)

    keys = sorted(groups)
    idx = {k: i + 1 for i, k in enumerate(keys)}      # 0 은 "어느 시군구도 아님"
    out = np.zeros((R, C), dtype=np.uint16)
    print(f"시군구 {len(keys)}개를 {R:,} x {C:,} 격자에 올린다")

    for n, k in enumerate(keys):
        polys = []
        for f in groups[k]:
            geom = f["geometry"]
            rings = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                     else [geom["coordinates"]])
            for poly in rings:
                lon, lat = np.asarray(poly[0]).T          # 바깥 고리만
                x, y = to5179.transform(lon, lat)
                polys.append(np.c_[(x - ox) / cell, (oyt - y) / cell])
        if not polys:
            continue
        allp = np.concatenate(polys)
        c0, r0 = np.floor(allp.min(0)).astype(int)
        c1, r1 = np.ceil(allp.max(0)).astype(int)
        c0, r0 = max(c0, 0), max(r0, 0)
        c1, r1 = min(c1, C), min(r1, R)
        if c1 <= c0 or r1 <= r0:
            continue
        # 시군구 하나짜리 작은 그림에 그린 뒤 제자리에 얹는다. 전국 크기로
        # 그리면 255 번 2 억 칸을 훑게 된다.
        im = Image.new("1", (c1 - c0, r1 - r0), 0)
        d = ImageDraw.Draw(im)
        for p in polys:
            d.polygon([(float(u - c0), float(v - r0)) for u, v in p], fill=1)
        m = np.array(im, dtype=bool)
        sub = out[r0:r1, c0:c1]
        sub[m & (sub == 0)] = idx[k]
        if (n + 1) % 40 == 0:
            print(f"  {n+1}/{len(keys)}", flush=True)

    np.save(a.out, out)
    a.table.write_text(json.dumps(
        {"index": {f"{s}|{g_}": i for (s, g_), i in idx.items()},
         "alias": SIDO_ALIAS}, ensure_ascii=False, indent=1), encoding="utf-8")
    el = np.load(G30 / "elevation.npy", mmap_mode="r")
    e = np.asarray(el[::11], dtype="float32"); land = np.isfinite(e) & (e > 0)
    cov = float((out[::11][land] > 0).mean())
    print(f"\n육지 중 시군구가 붙은 칸 {cov*100:.1f}%")
    print(f"  -> {a.out}, {a.table}")


if __name__ == "__main__":
    main()
