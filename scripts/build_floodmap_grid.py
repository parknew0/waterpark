#!/usr/bin/env python3
"""The government's own urban-inundation hazard map, on the model grid.

한강홍수통제소 publishes 도시침수지도: the depth and extent a hydraulic model
predicts when the storm drains are overwhelmed at a given return period. It is
the closest thing to an authoritative answer to the question this project asks,
which makes it worth two things -- a yardstick to measure the model against,
and a candidate feature.

The service returns one transparent mask per depth band rather than a single
styled picture, so each band is requested on its own and the class is known
exactly. No colour has to be guessed.
"""
from __future__ import annotations
import argparse, io, json, os, subprocess, time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
# 침수심 범례: 등급 -> 대표 깊이(cm)
BANDS = {"N330": 25, "N331": 75, "N332": 150, "N333": 350, "N334": 700}
BASE = "https://data.floodmap.go.kr/api/wms-service/{svc}"


def fetch(url: str, tries: int = 3) -> np.ndarray | None:
    for i in range(tries):
        r = subprocess.run(["/usr/bin/curl", "--silent", "--connect-timeout", "20",
                            "--max-time", "180", "--output", "-", "--config", "-"],
                           input=f'url = "{url}"\n'.encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode == 0 and r.stdout[:4] == b"\x89PNG":
            return np.array(Image.open(io.BytesIO(r.stdout)).convert("RGBA"))
        time.sleep(2 * (i + 1))
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--service", default="sa-cty-wms",
                    help="sa-cty-wms=도시침수, sa-ntn-wms=국가하천, sa-rgn-wms=지방하천")
    ap.add_argument("--freq", default="100", help="빈도(재현기간, 년)")
    ap.add_argument("--tile-px", type=int, default=1600)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    key = os.environ["FLOODMAP_API_KEY"]
    meta = json.loads((ROOT / "data/processed/serving-bundle/grid_meta.json")
                      .read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    x0, ytop = meta["origin_x"], meta["origin_y_top"]
    depth = np.zeros((R, C), dtype="int16")

    t = a.tile_px
    for r0 in range(0, R, t):
        for c0 in range(0, C, t):
            h, w = min(t, R - r0), min(t, C - c0)
            bx0 = x0 + c0 * cell
            bx1 = bx0 + w * cell
            by1 = ytop - r0 * cell
            by0 = by1 - h * cell
            for seg, cm in BANDS.items():
                url = (BASE.format(svc=a.service) +
                       f"?ServiceKey={key}&service=WMS&version=1.1.1&request=GetMap"
                       f"&Freq={a.freq}&SegCode={seg}&srs=EPSG:5179&format=image/png"
                       f"&transparent=TRUE&width={w}&height={h}"
                       f"&Bbox={bx0},{by0},{bx1},{by1}")
                img = fetch(url)
                if img is None:
                    continue
                hit = img[:, :, 3] > 0
                if not hit.any():
                    continue
                # 깊은 등급이 얕은 등급을 덮어쓴다
                block = depth[r0:r0 + h, c0:c0 + w]
                np.maximum(block, np.where(hit, cm, 0).astype("int16"), out=block)
        print(f"  행 {r0//t+1}/{(R+t-1)//t} 완료  침수 칸 누적 {int((depth>0).sum()):,}",
              flush=True)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, depth_cm=depth, service=a.service, freq=a.freq)
    n = int((depth > 0).sum())
    print(f"\n[결과] 침수 예상 칸 {n:,} ({n/(R*C)*100:.2f}%)  "
          f"깊이 중앙 {int(np.median(depth[depth>0])) if n else 0}cm  -> {a.out}")


if __name__ == "__main__":
    main()
