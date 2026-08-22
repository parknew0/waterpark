#!/usr/bin/env python3
"""Confirm underground parking for the buildings that actually flooded.

``analyze_basement_flood_overlap.py`` finds every building whose GIS record
says it has a basement and whose footprint sits inside a surveyed flood
polygon.  That answers "was this location flooded", not "is the basement a
car park" -- the GIS attribute ``A27`` counts underground floors without
saying what they are used for.

This collector closes that gap the same way the Gyeongbuk run did:

    1. 표제부 (getBrTitleInfo)   -> parcels whose register shows indoor
                                    parking area, i.e. probable car parks
    2. 층별개요 (getBrFlrOulnInfo) -> a basement floor whose 용도 contains
                                    "주차장" confirms it

The difference is scope.  The Gyeongbuk run screened every basement building
in the province (3,990 legal dongs).  Here only the flooded buildings matter,
because a building that never flooded contributes no label either way -- 659
legal dongs, roughly a sixth of the work.

Buildings whose 사용승인일자 is later than every flood event covering them are
dropped up front: they did not exist when the flood was surveyed.

The Building HUB API returns at most 100 rows per request and enforces a
daily quota, so every stage is resumable.  Completed work is appended to
JSONL and completion markers, and re-running skips whatever finished.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

from data_paths import INTERIM_BUILDING_REGISTER, RAW_BUILDING_REGISTER, ROOT

from download_gyeongbuk_building_register import (
    PAGE_SIZE,
    ApiClient,
    BudgetExceeded,
    CallBudget,
    append_jsonl,
    append_line,
    integer_or_none,
    load_completed,
    load_env_key,
    number,
    pnu_params,
    read_jsonl,
    row_pnu,
    write_csv,
)

OVERLAP_DIR = ROOT / "data/interim/vworld-buildings"
RAW_DIR = RAW_BUILDING_REGISTER / "flooded-national"
INTERIM_DIR = INTERIM_BUILDING_REGISTER
OUTPUT_DIR = ROOT / "outputs/flooded-building-register"

TARGET_CSV = INTERIM_DIR / "flooded_building_register_targets.csv"
TITLE_RAW = RAW_DIR / "title_rows.jsonl"
TITLE_COMPLETED = RAW_DIR / "title_completed_dongs.txt"
TITLE_FAILURES = RAW_DIR / "title_failures.jsonl"
FLOOR_RAW = RAW_DIR / "floor_rows.jsonl"
FLOOR_COMPLETED = RAW_DIR / "floor_completed_dongs.txt"
FLOOR_FAILURES = RAW_DIR / "floor_failures.jsonl"

CONFIRMED_CSV = INTERIM_DIR / "flooded_building_underground_parking.csv"
MANIFEST = OUTPUT_DIR / "flooded_building_register.manifest.json"
SAMPLE_CSV = OUTPUT_DIR / "flooded_building_underground_parking_sample.csv"

PARKING_WORD = "주차장"


def ensure_dirs() -> None:
    for directory in (RAW_DIR, INTERIM_DIR, OUTPUT_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def load_targets() -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    """Flooded buildings that existed at flood time, grouped by legal dong."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    skipped = Counter()
    for path in sorted(OVERLAP_DIR.glob("basement_flood_overlap_*_flooded.csv")):
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("existed_at_flood") == "NO":
                    skipped["approved_after_every_flood"] += 1
                    continue
                pnu = (row.get("pnu") or "").strip()
                if len(pnu) != 19 or not pnu.isdigit():
                    skipped["invalid_pnu"] += 1
                    continue
                key = f"{pnu}|{row.get('gis_building_id')}"
                if key in seen:
                    skipped["duplicate"] += 1
                    continue
                seen.add(key)
                rows.append(
                    {
                        "pnu": pnu,
                        "legal_dong_code": (row.get("legal_dong_code") or "").strip(),
                        "gis_building_id": row.get("gis_building_id", ""),
                        "building_use_name": row.get("building_use_name", ""),
                        "underground_floor_count": row.get("underground_floor_count", ""),
                        "approval_year": row.get("approval_year", ""),
                        "first_flood_year": row.get("first_flood_year", ""),
                        "last_flood_year": row.get("last_flood_year", ""),
                        "existed_at_flood": row.get("existed_at_flood", ""),
                        "longitude": row.get("longitude", ""),
                        "latitude": row.get("latitude", ""),
                    }
                )
    by_dong: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        # The API keys on sigungu+bjdong, which is the PNU's first ten digits.
        by_dong[row["pnu"][:10]].add(row["pnu"])
    if skipped:
        print(f"  [target] 제외: {dict(skipped)}", flush=True)
    return rows, by_dong


def collect_stage(
    stage: str,
    endpoint: str,
    by_dong: dict[str, set[str]],
    raw_path: Path,
    completed_path: Path,
    failure_path: Path,
    workers: int,
    budget: CallBudget,
    keep_pnus: set[str],
) -> dict[str, Any]:
    """Fetch one API endpoint for every pending legal dong.

    For each dong the cheaper of two access patterns is chosen.  A single
    unfiltered probe reports how many rows the dong holds; if paging through
    the whole dong costs fewer calls than querying each target parcel, the
    dong is paged and the probe's first page is reused.
    """
    completed = load_completed(completed_path)
    pending = [code for code in sorted(by_dong) if code not in completed]
    client = ApiClient(endpoint, load_env_key(), budget)
    failures: list[dict[str, str]] = []
    modes: Counter[str] = Counter()
    started = time.time()
    calls_at_start = budget.used
    done = 0

    print(
        f"[{stage}] 대상 법정동 {len(by_dong):,}개 중 남은 {len(pending):,}개"
        f" (완료 {len(completed):,})",
        flush=True,
    )

    def run(code: str) -> tuple[str, list[dict[str, Any]], str]:
        pnus = by_dong[code]
        params = {"sigunguCd": code[:5], "bjdongCd": code[5:]}
        first_rows, total = client.page(params, 1)
        pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1
        selected: list[dict[str, Any]] = []

        def keep(rows: Iterable[dict[str, Any]]) -> None:
            for row in rows:
                pnu = row_pnu(row)
                if pnu in keep_pnus:
                    item = dict(row)
                    item["pnu"] = pnu
                    selected.append(item)

        if pages <= len(pnus):
            keep(first_rows)
            for page_no in range(2, pages + 1):
                rows, _ = client.page(params, page_no)
                keep(rows)
            mode = "whole"
        else:
            for pnu in sorted(pnus):
                rows, _ = client.all_pages(pnu_params(pnu))
                keep(rows)
            mode = "parcel"
        return code, selected, mode

    stopped_for_budget = False
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(run, code): code for code in pending}
        try:
            for future in as_completed(futures):
                code = futures[future]
                try:
                    _, rows, mode = future.result()
                except BudgetExceeded:
                    stopped_for_budget = True
                    break
                except Exception as exc:  # noqa: BLE001 - recorded, not raised
                    failures.append({"legal_dong_code": code, "error": repr(exc)})
                    continue
                if rows:
                    append_jsonl(raw_path, rows)
                append_line(completed_path, code)
                modes[mode] += 1
                done += 1
                if done % 25 == 0 or done == len(pending):
                    used = budget.used - calls_at_start
                    elapsed = time.time() - started
                    print(
                        f"  [{stage}] {done:,}/{len(pending):,} 법정동"
                        f" | API 호출 {used:,} | {elapsed / 60:.1f}분",
                        flush=True,
                    )
        finally:
            if stopped_for_budget:
                for future in futures:
                    future.cancel()

    if failures:
        append_jsonl(failure_path, failures)

    return {
        "stage": stage,
        "endpoint": endpoint,
        "dongs_planned": len(by_dong),
        "dongs_completed_this_run": done,
        "dongs_remaining": len(pending) - done,
        "api_calls_used": budget.used - calls_at_start,
        "modes": dict(modes),
        "failures": len(failures),
        "stopped_for_budget": stopped_for_budget,
    }


def probable_parking_pks(title_rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Register PKs and parcels whose title row reports indoor parking area.

    Matches the Gyeongbuk screen: any indoor parking area or slot count is
    enough to make a parcel worth pulling floor detail for.  The floor stage
    is what actually confirms a *basement* car park.
    """
    pks: set[str] = set()
    pnus: set[str] = set()
    for row in title_rows:
        indoor = (
            number(row.get("indrMechUtcnt"))
            + number(row.get("indrAutoUtcnt"))
            + number(row.get("indrMechArea"))
            + number(row.get("indrAutoArea"))
        )
        if indoor <= 0:
            continue
        pk = str(row.get("mgmBldrgstPk") or "").strip()
        if pk:
            pks.add(pk)
        pnu = str(row.get("pnu") or "").strip()
        if pnu:
            pnus.add(pnu)
    return pks, pnus


def is_basement_parking(row: dict[str, Any]) -> bool:
    """A floor row that is underground and used as a car park."""
    floor_kind = str(row.get("flrGbCdNm") or "")
    floor_no = integer_or_none(row.get("flrNo"))
    underground = "지하" in floor_kind or (floor_no is not None and floor_no < 0)
    if not underground:
        return False
    use = f"{row.get('mainPurpsCdNm') or ''} {row.get('etcPurps') or ''}"
    return PARKING_WORD in use


def finalize(targets: list[dict[str, Any]]) -> dict[str, Any]:
    title_rows = read_jsonl(TITLE_RAW)
    floor_rows = read_jsonl(FLOOR_RAW)

    title_by_pnu: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in title_rows:
        pnu = str(row.get("pnu") or "").strip()
        if pnu:
            title_by_pnu[pnu].append(row)

    confirmed_pnus: set[str] = set()
    confirmed_evidence: dict[str, str] = {}
    for row in floor_rows:
        if not is_basement_parking(row):
            continue
        pnu = str(row.get("pnu") or row_pnu(row) or "").strip()
        if not pnu:
            continue
        confirmed_pnus.add(pnu)
        if pnu not in confirmed_evidence:
            confirmed_evidence[pnu] = (
                f"{row.get('flrGbCdNm') or ''} {row.get('flrNoNm') or row.get('flrNo') or ''}"
                f" / {row.get('mainPurpsCdNm') or ''}"
            ).strip()

    _, probable_pnus = probable_parking_pks(title_rows)

    status_counts: Counter[str] = Counter()
    out_rows: list[dict[str, Any]] = []
    for target in targets:
        pnu = target["pnu"]
        if pnu in confirmed_pnus:
            status = "CONFIRMED_BASEMENT_PARKING_USE"
        elif pnu in probable_pnus:
            status = "PROBABLE_NOT_CONFIRMED_IN_FLOOR_ROWS"
        elif pnu in title_by_pnu:
            status = "REGISTER_ROW_WITHOUT_INDOOR_PARKING"
        else:
            status = "NO_REGISTER_ROW_COLLECTED"
        status_counts[status] += 1
        item = dict(target)
        item["underground_parking_status"] = status
        item["underground_parking_confirmed"] = "Y" if status.startswith("CONFIRMED") else "N"
        item["underground_parking_evidence"] = confirmed_evidence.get(pnu, "")
        item["register_rows_on_parcel"] = len(title_by_pnu.get(pnu, []))
        out_rows.append(item)

    write_csv(
        CONFIRMED_CSV,
        out_rows,
        [
            "pnu",
            "gis_building_id",
            "legal_dong_code",
            "building_use_name",
            "underground_floor_count",
            "approval_year",
            "first_flood_year",
            "last_flood_year",
            "existed_at_flood",
            "underground_parking_status",
            "underground_parking_confirmed",
            "underground_parking_evidence",
            "register_rows_on_parcel",
            "longitude",
            "latitude",
        ],
    )
    write_csv(SAMPLE_CSV, out_rows[:200])

    confirmed = status_counts["CONFIRMED_BASEMENT_PARKING_USE"]
    summary = {
        "target_buildings": len(targets),
        "target_parcels": len({t["pnu"] for t in targets}),
        "title_rows_collected": len(title_rows),
        "floor_rows_collected": len(floor_rows),
        "probable_parcels": len(probable_pnus),
        "confirmed_parcels": len(confirmed_pnus),
        "status_counts": dict(status_counts),
        "confirmed_buildings": confirmed,
        "confirmed_share": round(confirmed / len(targets), 6) if targets else 0.0,
        "output_csv": str(CONFIRMED_CSV.relative_to(ROOT)),
        "notes": [
            "판정은 필지(PNU) 단위다. 같은 필지의 건물은 같은 판정을 공유한다.",
            "정답 라벨은 지표면 침수이며 지하주차장 침수 기록이 아니다.",
            "NO_REGISTER_ROW_COLLECTED는 미수집이며 지하주차장 없음이 아니다.",
        ],
    }
    MANIFEST.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        nargs="?",
        choices=("plan", "titles", "floors", "finalize", "all"),
        default="all",
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--call-budget", type=int, default=9700)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dirs()

    targets, by_dong = load_targets()
    if not targets:
        raise SystemExit(f"No flooded-building targets found under {OVERLAP_DIR}")
    keep_pnus = {t["pnu"] for t in targets}

    write_csv(TARGET_CSV, targets)
    print(
        f"[plan] 대상 건물 {len(targets):,}동 / 필지 {len(keep_pnus):,}개"
        f" / 법정동 {len(by_dong):,}개 -> {TARGET_CSV.relative_to(ROOT)}",
        flush=True,
    )
    if args.stage == "plan":
        return

    budget = CallBudget(args.call_budget)
    reports = []

    if args.stage in ("titles", "all"):
        reports.append(
            collect_stage(
                "titles",
                "getBrTitleInfo",
                by_dong,
                TITLE_RAW,
                TITLE_COMPLETED,
                TITLE_FAILURES,
                args.workers,
                budget,
                keep_pnus,
            )
        )

    if args.stage in ("floors", "all"):
        title_rows = read_jsonl(TITLE_RAW)
        _, probable_pnus = probable_parking_pks(title_rows)
        floor_by_dong: dict[str, set[str]] = defaultdict(set)
        for pnu in probable_pnus:
            if pnu in keep_pnus:
                floor_by_dong[pnu[:10]].add(pnu)
        print(
            f"[floors] 옥내주차 있는 대상 필지 {sum(len(v) for v in floor_by_dong.values()):,}개"
            f" / 법정동 {len(floor_by_dong):,}개",
            flush=True,
        )
        if floor_by_dong:
            reports.append(
                collect_stage(
                    "floors",
                    "getBrFlrOulnInfo",
                    floor_by_dong,
                    FLOOR_RAW,
                    FLOOR_COMPLETED,
                    FLOOR_FAILURES,
                    args.workers,
                    budget,
                    keep_pnus,
                )
            )

    if args.stage in ("finalize", "all"):
        summary = finalize(targets)
        print()
        print("[결과] 침수 건물 지하주차장 확정")
        print(f"  대상 건물            : {summary['target_buildings']:,}동")
        print(f"  표제부 수집          : {summary['title_rows_collected']:,}행")
        print(f"  층별개요 수집        : {summary['floor_rows_collected']:,}행")
        print(f"  옥내주차 있는 필지    : {summary['probable_parcels']:,}개")
        print(f"  지하주차장 확정 건물  : {summary['confirmed_buildings']:,}동")
        print(f"  저장                : {summary['output_csv']}")

    for report in reports:
        remaining = report["dongs_remaining"]
        print(
            f"\n[{report['stage']}] API 호출 {report['api_calls_used']:,}"
            f" | 남은 법정동 {remaining:,}"
            f" | 방식 {report['modes']}"
            f" | 실패 {report['failures']}"
        )
        if report["stopped_for_budget"]:
            print(
                f"  일일 호출 한도에 도달했다. 같은 명령을 다시 실행하면"
                f" 남은 {remaining:,}개 법정동부터 이어서 수집한다."
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중단됨. 같은 명령으로 재실행하면 이어서 수집한다.", file=sys.stderr)
        raise SystemExit(130)
