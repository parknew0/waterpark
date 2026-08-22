#!/usr/bin/env python3
"""Roll the per-province basement × flood overlap results into one picture.

``analyze_basement_flood_overlap.py`` answers the question one province at a
time.  This script reads every result it produced and reports the numbers that
actually decide whether the nationwide training table is worth building:

* how many flooded basement buildings exist in total,
* how they split between 반지하 (지하 1층, mostly 단독주택) and the deeper
  structures that can hold an underground car park,
* how many are expected to be *confirmed* underground parking once the
  Building HUB register is collected.

The confirmation estimate reuses the per-use rates measured on Gyeongbuk,
where the register was actually collected.  It is an estimate and is labelled
as one; only the Building HUB collection can settle the real number.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from data_paths import ROOT

OVERLAP_DIR = ROOT / "data/interim/vworld-buildings"
GYEONGBUK_FEATURES = (
    ROOT / "data/processed/buildings/gyeongbuk_building_underground_parking_features.csv"
)
OUT_JSON = OVERLAP_DIR / "basement_flood_overlap_national_summary.json"

CONFIRMED_STATUS = "CONFIRMED_BASEMENT_PARKING_USE"
# Below this many Gyeongbuk buildings a per-use rate is too noisy to project.
MIN_RATE_SAMPLE = 50


def gyeongbuk_confirmation_rates() -> tuple[dict[str, float], float]:
    """Measured share of basement buildings confirmed as underground parking."""
    totals: Counter[str] = Counter()
    confirmed: Counter[str] = Counter()
    with GYEONGBUK_FEATURES.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            use = (row.get("gis_use_name") or "").strip() or "(미기재)"
            totals[use] += 1
            if row.get("underground_parking_status") == CONFIRMED_STATUS:
                confirmed[use] += 1
    rates = {
        use: confirmed[use] / count
        for use, count in totals.items()
        if count >= MIN_RATE_SAMPLE
    }
    overall = sum(confirmed.values()) / sum(totals.values()) if totals else 0.0
    return rates, overall


def load_results() -> list[dict[str, Any]]:
    results = []
    for path in sorted(OVERLAP_DIR.glob("basement_flood_overlap_*.json")):
        if not re.match(r"basement_flood_overlap_\d{2}\.json$", path.name):
            continue
        results.append(json.loads(path.read_text(encoding="utf-8")))
    return results


def flooded_rows(province_code: str):
    path = OVERLAP_DIR / f"basement_flood_overlap_{province_code}_flooded.csv"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def main() -> None:
    results = load_results()
    if not results:
        raise SystemExit(f"No overlap results under {OVERLAP_DIR}")

    rates, overall_rate = gyeongbuk_confirmation_rates()

    use_counts: Counter[str] = Counter()
    depth_by_group: dict[str, Counter[int]] = defaultdict(Counter)
    per_province: list[dict[str, Any]] = []
    timeline_total: Counter[str] = Counter()

    for result in results:
        code = result["province_code"]
        rows = list(flooded_rows(code))
        province_use: Counter[str] = Counter()
        deep = 0
        for row in rows:
            use = (row.get("building_use_name") or "").strip() or "(미기재)"
            floors = int(row["underground_floor_count"])
            use_counts[use] += 1
            province_use[use] += 1
            group = "단독주택" if use == "단독주택" else "그 외"
            depth_by_group[group][floors] += 1
            if floors >= 2:
                deep += 1

        for key, value in (result.get("timeline") or {}).items():
            timeline_total[key] += value

        expected = sum(
            count * rates[use] for use, count in province_use.items() if use in rates
        )
        per_province.append(
            {
                "province_code": code,
                "province_name": result["province_name"],
                "flood_polygons": result["flood"]["province_polygons"],
                "basement_buildings": result["totals"]["basement_buildings"],
                "flooded": result["totals"]["inside_flood_polygon"],
                "flooded_rate": result["inside_rate"],
                "flooded_deep_2f_plus": deep,
                "expected_confirmed_parking": round(expected, 1),
                "csv_present": bool(rows),
            }
        )

    per_province.sort(key=lambda item: item["flooded"], reverse=True)

    total_flooded = sum(item["flooded"] for item in per_province)
    total_basement = sum(item["basement_buildings"] for item in per_province)
    total_deep = sum(item["flooded_deep_2f_plus"] for item in per_province)
    total_expected = sum(item["expected_confirmed_parking"] for item in per_province)
    covered = sum(count for use, count in use_counts.items() if use in rates)

    print("=" * 86)
    print("전국 지하층 건물 × 침수흔적 겹침 종합")
    print("=" * 86)
    header = (
        f"{'시도':<20}{'침수Poly':>9}{'지하층건물':>11}"
        f"{'침수내부':>9}{'비율':>8}{'지하2층+':>9}{'기대주차':>9}"
    )
    print(header)
    print("-" * 86)
    for item in per_province:
        print(
            f"{item['province_name']:<20}"
            f"{item['flood_polygons']:>9,}"
            f"{item['basement_buildings']:>11,}"
            f"{item['flooded']:>9,}"
            f"{item['flooded_rate'] * 100:>7.2f}%"
            f"{item['flooded_deep_2f_plus']:>9,}"
            f"{item['expected_confirmed_parking']:>9,.0f}"
        )
    print("-" * 86)
    rate = total_flooded / total_basement * 100 if total_basement else 0.0
    print(
        f"{'전국 합계':<20}"
        f"{sum(i['flood_polygons'] for i in per_province):>9,}"
        f"{total_basement:>11,}"
        f"{total_flooded:>9,}"
        f"{rate:>7.2f}%"
        f"{total_deep:>9,}"
        f"{total_expected:>9,.0f}"
    )
    print("=" * 86)

    print("\n[용도 분포] 침수 Polygon 내부 지하층 건물")
    for use, count in use_counts.most_common(12):
        share = count / total_flooded * 100 if total_flooded else 0.0
        rate_text = f"{rates[use] * 100:.1f}%" if use in rates else "표본부족"
        print(f"  {count:>7,}동 ({share:>5.1f}%)  {use:<18} 경북 주차확정률 {rate_text}")

    print("\n[지하층 깊이] 반지하와 깊은 구조물 구분")
    for group, counter in sorted(depth_by_group.items()):
        total = sum(counter.values())
        one = counter[1]
        deep = total - one
        print(
            f"  {group:<10} 합계 {total:>7,}동 | 지하1층 {one:>7,} ({one/total*100:>5.1f}%)"
            f" | 지하2층+ {deep:>6,} ({deep/total*100:>5.1f}%)"
        )

    checked = (
        timeline_total["approved_after_last_flood"]
        + timeline_total["approved_before_or_same_year"]
    )
    if checked:
        after_last = timeline_total["approved_after_last_flood"]
        after_first = timeline_total["approved_after_first_flood"]
        print("\n[시점 검증] 2026 건물 스냅샷 대 2002~2022 침수 사건")
        print(f"  준공일로 판정 가능        : {checked:,}동")
        print(
            f"  덮은 사건 전부보다 신축    : {after_last:,}동"
            f" ({after_last / checked * 100:.2f}%)  → 학습에서 제외해야 함"
        )
        print(
            f"  일부 사건보다만 신축      : {after_first:,}동"
            f" ({after_first / checked * 100:.2f}%)  → 건물×사건 표에서 해당 행만 제외"
        )
        print(f"  준공일 없음              : {timeline_total['approval_date_missing']:,}동")
        print(f"  침수 연도 불명            : {timeline_total['flood_year_unknown']:,}동")

    print("\n[기대 지하주차장 확정 수] 경북 용도별 확정률 적용")
    print(f"  침수 지하층 건물          : {total_flooded:,}동")
    print(f"  용도별 확정률 적용 가능    : {covered:,}동")
    print(f"  기대 확정 지하주차장       : 약 {total_expected:,.0f}동")
    print(f"  경북 실제 확정(기존)       : 9동")
    if total_expected:
        print(f"  배수                     : {total_expected / 9:,.0f}배")
    print("\n  ※ 추정이다. 실제 확정 수는 건축HUB 표제부·층별개요 수집으로만 확정된다.")

    OUT_JSON.write_text(
        json.dumps(
            {
                "per_province": per_province,
                "building_use_counts": dict(use_counts.most_common()),
                "underground_depth_by_group": {
                    group: dict(sorted(counter.items()))
                    for group, counter in depth_by_group.items()
                },
                "gyeongbuk_confirmation_rates": {
                    use: round(rate, 6) for use, rate in sorted(rates.items())
                },
                "gyeongbuk_overall_confirmation_rate": round(overall_rate, 6),
                "timeline_total": dict(timeline_total),
                "totals": {
                    "flood_polygons": sum(i["flood_polygons"] for i in per_province),
                    "basement_buildings": total_basement,
                    "flooded": total_flooded,
                    "flooded_deep_2f_plus": total_deep,
                    "expected_confirmed_parking": round(total_expected, 1),
                    "use_rate_covered": covered,
                },
                "notes": [
                    "expected_confirmed_parking는 경북에서 측정한 용도별 확정률을 다른 시도에 적용한 추정이다.",
                    f"표본 {MIN_RATE_SAMPLE}동 미만인 용도는 확정률을 적용하지 않았다.",
                    "정답 라벨은 지표면 침수이며 지하주차장 침수 기록이 아니다.",
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n저장: {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
