#!/usr/bin/env python3
"""관거밀도를 격자에 굽는다. 시군구 경계로 이름과 좌표를 잇는다.

하수도 통계는 시군구 '이름'으로만 오고 우리 공간 자료는 '코드'만 가지고
있어서 둘이 만나지 못했다. VWorld 시군구 경계가 코드와 이름을 한 레코드에
담고 있어 다리가 된다.

해상도는 시군구다. 500 km2에 값 하나이므로 30 m 격자에서는 거의 상수이고,
지형에서 읽을 수 없는 배수 능력을 담는 대신 '어느 지역인가'를 가리키는
표식으로 작동할 위험이 있다. 그래서 이 변수는 넣고 빼며 검증해야지, 논문에
나온다는 이유만으로 채택할 수 없다.
"""
from __future__ import annotations
import argparse, json, os, time, urllib.parse, urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.vworld.kr/req/data"


def fetch_sgg(key: str) -> list[dict]:
    """전국 시군구 경계. 한 번에 다 주지 않으므로 격자로 나눠 훑는다."""
    seen: dict[str, dict] = {}
    for lon0 in np.arange(125.0, 130.0, 0.5):
        for lat0 in np.arange(33.0, 38.7, 0.5):
            box = f"BOX({lon0},{lat0},{lon0+0.5},{lat0+0.5})"
            u = (f"{API}?service=data&request=GetFeature&data=LT_C_ADSIGG_INFO"
                 f"&key={key}&size=1000&format=json&geomFilter={urllib.parse.quote(box)}")
            try:
                d = json.loads(urllib.request.urlopen(u, timeout=60).read())
            except Exception:
                continue
            r = d.get("response", {})
            if r.get("status") != "OK":
                continue
            for f in r["result"]["featureCollection"]["features"]:
                seen.setdefault(f["properties"]["sig_cd"], f)
            time.sleep(0.1)
        print(f"  경도 {lon0:.1f} 까지 누적 시군구 {len(seen)}", flush=True)
    return list(seen.values())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid", type=Path, default=ROOT / "data/interim/grid30")
    a = ap.parse_args()
    key = os.environ["VWORLD_API_KEY"]
    cache = ROOT / "data/interim/drainage/sgg_boundaries.json"
    if cache.exists():
        feats = json.loads(cache.read_text(encoding="utf-8"))
    else:
        feats = fetch_sgg(key)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(feats, ensure_ascii=False), encoding="utf-8")
    print(f"시군구 경계 {len(feats)}곳")

    sew = pd.read_csv(ROOT / "data/interim/drainage/sewer_by_sgg.csv")
    # 하수도 통계는 (시도, 구군) 이름, 경계는 full_nm("경기도 성남시 수정구").
    # 구 단위까지 나뉜 곳은 시 이름으로도 찾을 수 있게 둘 다 담는다.
    dens: dict[str, float] = {}
    for r in sew.itertuples():
        dens[f"{r.sido} {r.sgg}"] = r.sewer_density_m_per_km2
        dens[str(r.sgg)] = r.sewer_density_m_per_km2

    meta = json.loads((a.grid / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    T = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    out = np.full((R, C), np.nan, dtype="float32")

    matched = 0
    for f in feats:
        name = f["properties"]["full_nm"]
        v = dens.get(name)
        if v is None:
            parts = name.split()
            for cand in (" ".join(parts[:2]), parts[-1], " ".join(parts[1:])):
                v = dens.get(cand)
                if v is not None:
                    break
        if v is None:
            continue
        matched += 1
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            ring = np.array(poly[0], dtype="float64")
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
            block = out[r0:r1, c0:c1]
            block[inside.reshape(block.shape)] = v
    np.save(a.grid / "sewer_density.npy", out)
    got = np.isfinite(out)
    print(f"이름이 이어진 시군구 {matched}/{len(feats)}")
    print(f"값이 채워진 칸 {got.mean()*100:.1f}%  중앙 {np.nanmedian(out):,.0f} m/km2")


if __name__ == "__main__":
    main()
