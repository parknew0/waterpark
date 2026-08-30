#!/usr/bin/env python3
"""토양 특성을 30 m 격자에 굽는다. 우리에게 없던 축.

지금 쓰는 변수 어디에도 "이 땅이 물을 얼마나 흡수하는가"가 없다. 불투수율은
덮여 있는지를 재지, 덮이지 않은 땅이 물을 머금는지는 재지 않는다. 배수등급은
그 질문에 직접 답한다.

국토교통부 토양환경정보도(농촌진흥청 흙토람 기반)를 VWorld 벡터 API로 받는다.
공공저작물 제1유형이라 출처만 밝히면 가공에 제약이 없다.

  soil_drain   배수등급 1(매우양호) ~ 6(매우불량)
  soil_depth   유효토심 등급
  soil_texture 심토토성 등급
  soil_stone   표토 자갈함량 등급

한 번에 1,000개까지만 주므로 격자로 훑고, 폴리곤을 칸에 칠한다. 값이 없는
칸은 그대로 비운다 -- 흙토람은 농업용 토양도라 시가지 조사가 성길 수 있고,
비었다는 사실 자체가 정보다.
"""
from __future__ import annotations
import argparse, json, os, time, urllib.parse, urllib.request
from pathlib import Path

import numpy as np
import pyproj
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.vworld.kr/req/data"
LAYERS = {"soil_drain": ("LT_C_ASITSOILDRA", "code_dc"),
          "soil_depth": ("LT_C_ASITSOILDEP", "code_ad"),
          "soil_texture": ("LT_C_ASITDEEPSOIL", "code_st"),
          "soil_stone": ("LT_C_ASITSURSTON", "code_sg")}


def fetch(layer: str, key: str, box: str, page: int, tries: int = 3):
    u = (f"{API}?service=data&request=GetFeature&data={layer}&key={key}"
         f"&size=1000&page={page}&format=json&geomFilter={urllib.parse.quote(box)}")
    for i in range(tries):
        try:
            d = json.loads(urllib.request.urlopen(u, timeout=60).read())
            r = d.get("response", {})
            if r.get("status") == "OK":
                return r["result"]["featureCollection"]["features"], r.get("record", {})
            if r.get("status") == "NOT_FOUND":
                return [], {}
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None, {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid", type=Path, default=ROOT / "data/interim/grid30")
    ap.add_argument("--step", type=float, default=0.1, help="훑는 격자 크기(도)")
    a = ap.parse_args()
    key = os.environ["VWORLD_API_KEY"]
    meta = json.loads((a.grid / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    T = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    out = {n: np.full((R, C), np.nan, dtype="float32") for n in LAYERS}
    lons = np.arange(125.0, 130.0, a.step)
    lats = np.arange(33.0, 38.7, a.step)
    total = len(lons) * len(lats)
    done = 0
    for name, (layer, field) in LAYERS.items():
        arr = out[name]
        painted = 0
        for lo in lons:
            for la in lats:
                # geomFilter 는 BOX(...) 형태여야 한다. 좌표만 보내면
                # INVALID_RANGE 로 조용히 빈 결과가 돌아온다.
                box = f"BOX({lo},{la},{lo+a.step},{la+a.step})"
                page = 1
                while True:
                    feats, rec = fetch(layer, key, box, page)
                    if not feats:
                        break
                    for f in feats:
                        v = f["properties"].get(field)
                        try:
                            v = float(v)
                        except (TypeError, ValueError):
                            continue
                        g = f["geometry"]
                        polys = (g["coordinates"] if g["type"] == "MultiPolygon"
                                 else [g["coordinates"]])
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
                            inside = MplPath(np.c_[x, y]).contains_points(
                                np.c_[XX.ravel(), YY.ravel()])
                            blk = arr[r0:r1, c0:c1]
                            blk[inside.reshape(blk.shape)] = v
                            painted += int(inside.sum())
                    if len(feats) < 1000:
                        break
                    page += 1
                done += 1
                if done % 200 == 0:
                    print(f"  {name}: 상자 {done % (total+1)}/{total}  칸 {painted:,}",
                          flush=True)
        got = np.isfinite(arr)
        print(f"[{name}] 값이 있는 칸 {got.sum():,} ({got.mean()*100:.1f}%)", flush=True)
        np.save(a.grid / f"{name}.npy", arr)
        done = 0
    print("완료")


if __name__ == "__main__":
    main()
