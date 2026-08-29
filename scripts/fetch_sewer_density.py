#!/usr/bin/env python3
"""관거밀도: 처리구역 넓이당 하수관 길이.

국내 연구가 한계강우량을 정하는 유역 인자로 관거밀도, 빗물받이 밀도,
유역경사, 불투수율, 펌프장 배제능력 다섯을 꼽는데, 관거밀도만은 대용할
것이 없었다. 배수 능력을 직접 재는 유일한 공개 자료이기 때문이다.

공간 해상도는 하수처리구역 단위라 30 m 격자에 비하면 거칠다. 그래도
"이 동네 배수관이 촘촘한가"는 지형에서 절대 읽을 수 없는 정보다.
"""
from __future__ import annotations
import argparse, csv, json, os, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UDDI = "288c613e-60e7-4e6a-a51b-87c38e42caf6"      # 2024-12-31 기준
BASE = f"https://api.odcloud.kr/api/15118453/v1/uddi:{UDDI}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data/interim/drainage/sewer_by_sgg.csv")
    a = ap.parse_args()
    key = urllib.parse.quote(os.environ["DATA_GO_KR_PUMP_KEY"], safe="")
    rows, page = [], 1
    while True:
        u = f"{BASE}?serviceKey={key}&page={page}&perPage=1000"
        d = json.loads(urllib.request.urlopen(u, timeout=90).read())
        got = d.get("data", [])
        if not got:
            break
        rows.extend(got)
        print(f"  {page}쪽 누적 {len(rows):,}/{d.get('totalCount')}", flush=True)
        if len(rows) >= int(d.get("totalCount", 0)):
            break
        page += 1

    # 처리구역이 여러 개인 시군구는 합산한 뒤 나눈다: 구역마다 따로 나누면
    # 작은 구역의 밀도가 전체를 대표해 버린다.
    agg: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        sido = str(r.get("시도", "")).strip()
        sgg = str(r.get("구군", "")).strip()
        if not sido or not sgg:
            continue
        try:
            length = float(r.get("하수관로_총시설연장") or 0)     # m
            area = float(r.get("처리구역면적_합계") or 0)          # km2
        except (TypeError, ValueError):
            continue
        cur = agg.setdefault((sido, sgg), [0.0, 0.0])
        cur[0] += length
        cur[1] += area

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["sido", "sgg", "sewer_m", "area_km2", "sewer_density_m_per_km2"])
        n = 0
        for (sido, sgg), (length, area) in sorted(agg.items()):
            if area <= 0:
                continue
            w.writerow([sido, sgg, round(length, 1), round(area, 3),
                        round(length / area, 1)])
            n += 1
    print(f"[결과] 시군구 {n}곳 -> {a.out}")
    dens = sorted((l / ar) for (l, ar) in agg.values() if ar > 0)
    if dens:
        mid = dens[len(dens) // 2]
        print(f"  관거밀도 중앙 {mid:,.0f} m/km2  "
              f"최소 {dens[0]:,.0f}  최대 {dens[-1]:,.0f}")


if __name__ == "__main__":
    main()
