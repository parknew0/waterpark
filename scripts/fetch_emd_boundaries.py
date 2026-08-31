#!/usr/bin/env python3
"""읍면동 경계를 받는다. 기사 채점을 열 배 가늘게 하기 위한 것.

시군구 단위 기사 채점에서 우리 모델은 강수량만 쓴 것보다 나빴다. 남은 해석은
"시군구끼리 비교하는 시험인데 우리 모델은 한 동네 안에서 칸끼리 가리도록
배웠다"인데, 그것을 확인하려면 더 가는 눈금이 필요하다.

기사 14,287 건 중 5,802 건(41%) 이 본문에 읍면동 이름을 담고 있다. 읍면동은
시군구보다 열 배쯤 좁다. 같은 이름이 전국에 여럿 있으므로 (신촌동만 여러 곳)
시군구와 짝지어야 한다 -- full_nm 에 시도·시군구가 함께 들어 있다.

VWorld 는 한 번에 좁은 상자만 주므로 전국을 격자로 나눠 훑는다.
"""
from __future__ import annotations
import argparse, json, os, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYER = "LT_C_ADEMD_INFO"


def get(url, tries=3):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(url, timeout=45).read())
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step", type=float, default=0.12)
    ap.add_argument("--out", type=Path, default=ROOT / "data/interim/emd_boundaries.json")
    a = ap.parse_args()
    key = os.environ["VWORLD_API_KEY"]

    seen: dict[str, dict] = {}
    boxes = []
    lo = 125.9
    while lo < 129.7:
        la = 33.0
        while la < 38.7:
            boxes.append((round(lo, 3), round(la, 3)))
            la += a.step
        lo += a.step
    print(f"상자 {len(boxes)}개로 전국을 훑는다 (한 변 {a.step}도)")

    t0 = time.time()
    for n, (lo, la) in enumerate(boxes):
        page = 1
        while True:
            p = {"service": "data", "request": "GetFeature", "data": LAYER, "key": key,
                 "domain": "localhost", "format": "json", "size": "1000", "page": str(page),
                 "geomFilter": f"BOX({lo},{la},{lo+a.step},{la+a.step})"}
            d = get("https://api.vworld.kr/req/data?" + urllib.parse.urlencode(p))
            r = (d or {}).get("response", {})
            if r.get("status") != "OK":
                break
            fc = r.get("result", {}).get("featureCollection", {}).get("features", [])
            for f in fc:
                cd = f["properties"].get("emd_cd")
                if cd and cd not in seen:
                    seen[cd] = f
            if len(fc) < 1000:
                break
            page += 1
        if (n + 1) % 50 == 0:
            print(f"  상자 {n+1}/{len(boxes)}  읍면동 {len(seen):,}개  "
                  f"({(time.time()-t0)/60:.0f}분)", flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(list(seen.values()), ensure_ascii=False), encoding="utf-8")
    print(f"\n읍면동 {len(seen):,}개 -> {a.out}  ({a.out.stat().st_size/1e6:.0f} MB)")


if __name__ == "__main__":
    main()
