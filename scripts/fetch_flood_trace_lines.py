#!/usr/bin/env python3
"""침수흔적도의 심선·위선을 받는다. 2023 년 라벨이 여기에만 있다.

본 침수흔적도 API(DSSP-IF-00117) 는 2022 년에서 끊긴다. Esri 미러도 같다.
그런데 2025 년에 따로 올라온 두 자료 -- 심선(침수심 측선)과 위선(침수위 측선)
-- 에는 2023 년이 들어 있다. 심선 6,416 건, 위선 5,281 건이다.

폴리곤이 아니라 측선의 점이지만 좌표(EPSG:3857)와 침수 시각이 있고, 위선에는
침수 원인("하수역류로 인한 침수")과 평균 침수위까지 있다. 우리가 라벨로 쓰는
데는 점이면 충분하다 -- 링 센서스는 어차피 점 둘레에 고리를 두른다.
"""
from __future__ import annotations
import argparse, json, os, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETS = {"shim": ("DSSP-IF-20678", "SAFETYDATA_FLOOD_SHIM_KEY", "심선"),
        "wiseon": ("DSSP-IF-20679", "SAFETYDATA_FLOOD_WISEON_KEY", "위선")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "data/raw/flood-trace")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for name, (sid, keyname, label) in SETS.items():
        key = os.environ[keyname]
        rows, t0 = [], time.time()
        for pg in range(1, 500):
            p = {"serviceKey": key, "pageNo": str(pg), "numOfRows": "1000",
                 "returnType": "json"}
            u = f"https://www.safetydata.go.kr/V2/api/{sid}?" + urllib.parse.urlencode(p)
            for tries in range(3):
                try:
                    b = json.loads(urllib.request.urlopen(u, timeout=90).read()).get("body") or []
                    break
                except Exception:
                    if tries == 2:
                        b = []
                    time.sleep(2)
            if not b:
                break
            rows.extend(b)
            if pg % 10 == 0:
                print(f"  {label} {pg}쪽 {len(rows):,}건 ({(time.time()-t0)/60:.0f}분)", flush=True)
        f = a.out / f"flood_trace_{name}.json"
        f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"{label}: {len(rows):,}건 -> {f}  ({f.stat().st_size/1e6:.0f} MB)")


if __name__ == "__main__":
    main()
