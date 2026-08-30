#!/usr/bin/env python3
"""하천 수위. 우리 변수 중 시간에 따라 변하는 두 번째 축.

지금 쓰는 21개 변수 가운데 사건마다 값이 달라지는 것은 강수 둘뿐이고,
나머지 열아홉은 고정이다. 같은 땅에 같은 비가 왔는데 결과가 달랐던 경우를
설명할 수단이 없다는 뜻이다.

수위는 물리도 분명하다. 하천이 높으면 하수관이 물을 내보내지 못한다 --
내수배제 불량이다. 하천이 넘치지 않아도 도시가 잠기는 경로이고, 우리는
하천범람 라벨을 이미 뺐으므로 남은 라벨에 정확히 해당한다.

WAMIS 는 인증키를 요구하지 않고 시간별 수위를 준다. 관측소 제원에 위경도가
도-분-초로 들어 있어 십진수로 바꿔 쓴다.
"""
from __future__ import annotations
import argparse, json, re, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://www.wamis.go.kr:8080/wamis/openapi/wkw"


def get(url: str, tries: int = 3):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(url, timeout=45).read())
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def dms(v: str) -> float | None:
    """'126-57-24' -> 126.9567. 빈 값과 형식 이탈은 버린다."""
    m = re.match(r"^\s*(\d+)-(\d+)-(\d+(?:\.\d+)?)", str(v or ""))
    if not m:
        return None
    d, mi, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return d + mi / 60 + s / 3600


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "data/interim/waterlevel")
    ap.add_argument("--events", type=Path, default=ROOT / "config/radar/flood_hours.json",
                    help="주면 그 사건일들의 시간별 수위까지 받는다")
    ap.add_argument("--stations-only", action="store_true")
    ap.add_argument("--only-days", type=Path,
                    help="이 목록의 날짜만 받는다. 레이더가 있는 사건만 쓰면 214일이 131일이 된다")
    ap.add_argument("--workers", type=int, default=12,
                    help="관측소를 하나씩 부르면 날짜당 8분이라 214일에 28시간 걸린다")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    listing = get(f"{BASE}/wl_dubwlobs?output=json")
    obs = [r for r in listing["list"] if r.get("obscd")]
    print(f"관측소 {len(obs):,}곳, 제원 조회 중", flush=True)

    rows = []
    for i, r in enumerate(obs):
        d = get(f"{BASE}/wl_obsinfo?obscd={r['obscd']}&output=json", tries=2)
        if not d or not d.get("list"):
            continue
        info = d["list"][0]
        lon, lat = dms(info.get("lon")), dms(info.get("lat"))
        if lon is None or lat is None or not (124 < lon < 132 and 33 < lat < 39):
            continue
        rows.append({"obscd": r["obscd"], "obsnm": info.get("obsnm", ""),
                     "lon": round(lon, 6), "lat": round(lat, 6),
                     "river": info.get("rivnm", ""),
                     "basin_km2": info.get("bsnara", ""),
                     "start": info.get("obsopndt", "")})
        if (i + 1) % 200 == 0:
            print(f"  {i+1:,}/{len(obs):,}  좌표 확보 {len(rows):,}", flush=True)

    out = a.out / "stations.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[결과] 좌표 있는 관측소 {len(rows):,}곳 -> {out}")
    if a.stations_only or not a.events:
        return

    # 사건일의 시간별 수위. 침수 시각에 맞춰 읽으려면 일 단위로는 부족하다.
    import datetime
    days = sorted(json.loads(a.events.read_text(encoding="utf-8")))
    if a.only_days:
        want = set(json.loads(a.only_days.read_text(encoding="utf-8")))
        days = [d for d in days if d in want]
    print(f"\n사건 {len(days)}일 x 관측소 {len(rows):,}곳 수위 수집", flush=True)
    for di, day in enumerate(days):
        target = a.out / f"wl_{day}.json"
        if target.exists():
            continue
        d0 = (datetime.datetime.strptime(day, "%Y%m%d")
              - datetime.timedelta(days=1)).strftime("%Y%m%d")
        def one(r):
            j = get(f"{BASE}/wl_hrdata?obscd={r['obscd']}"
                    f"&startdt={d0}&enddt={day}&output=json", tries=2)
            if not j or not j.get("list"):
                return None
            series = {x["ymdh"]: x["wl"] for x in j["list"]
                      if x.get("wl") not in (None, "")}
            return (r["obscd"], series) if series else None

        from concurrent.futures import ThreadPoolExecutor
        got = {}
        with ThreadPoolExecutor(a.workers) as pool:
            for res in pool.map(one, rows):
                if res:
                    got[res[0]] = res[1]
        target.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
        print(f"  {day} ({di+1}/{len(days)})  관측소 {len(got):,}곳", flush=True)
    print("수위 수집 완료")


if __name__ == "__main__":
    main()
