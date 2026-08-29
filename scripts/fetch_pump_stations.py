#!/usr/bin/env python3
"""전국 배수펌프장 위치. 침수 논문이 꼽는 배수 인자 중 하나.

국내 연구가 한계강우량을 정하는 유역 인자로 관거밀도, 빗물받이 밀도,
유역경사, 불투수율, 펌프장 배제능력 다섯을 꼽는데, 우리에게는 뒤의 둘밖에
없었다. 펌프장은 공공데이터 표준데이터로 전국 좌표가 공개돼 있다.

펌프장이 가까이 있다는 것은 두 가지를 동시에 뜻한다 -- 물을 퍼낼 수단이
있다는 것과, 애초에 퍼내야 할 만큼 잠기는 땅이라는 것. 어느 쪽이 이기는지는
모델이 판단할 일이므로 거리를 그대로 넣는다.
"""
from __future__ import annotations
import argparse, json, os, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.data.go.kr/openapi/tn_pubr_public_pump_api"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data/interim/drainage/pump_stations.csv")
    a = ap.parse_args()
    key = urllib.parse.quote(os.environ["DATA_GO_KR_PUMP_KEY"], safe="")
    rows, page = [], 1
    while True:
        u = f"{BASE}?serviceKey={key}&pageNo={page}&numOfRows=1000&type=json"
        d = json.loads(urllib.request.urlopen(u, timeout=90).read())
        # 이 API는 response 래퍼 없이 header/body가 최상위에 온다
        body = d.get("body", d.get("response", {}).get("body", {}))
        items = body.get("items", {})
        items = items.get("item", []) if isinstance(items, dict) else items
        if not items:
            break
        rows.extend(items)
        print(f"  {page}쪽 누적 {len(rows):,}", flush=True)
        if len(items) < 1000:
            break
        page += 1
        time.sleep(0.3)
    import csv
    a.out.parent.mkdir(parents=True, exist_ok=True)
    keep = [r for r in rows if r.get("lat") and r.get("lot")]
    if not keep:
        raise SystemExit("받은 자료가 없다")
    with a.out.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(keep[0].keys()))
        w.writeheader(); w.writerows(keep)
    print(f"[결과] 펌프장 {len(keep):,}곳 (좌표 있는 것) -> {a.out}")
    import collections
    c = collections.Counter(r.get("ctpvNm", "") for r in keep)
    print("  시도별:", dict(sorted(c.items(), key=lambda x: -x[1])[:8]))


if __name__ == "__main__":
    main()
