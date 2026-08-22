#!/usr/bin/env python3
"""Download the Gyeongbuk building-register rows needed by Waterpark.

The Building HUB API returns at most 100 rows per request and requires both a
five-digit sigungu code and a five-digit bjdong code.  A full blind download of
Gyeongbuk can therefore exceed the daily quota.  This collector first reads
the locally downloaded VWorld GIS building DBF files, keeps buildings whose
official GIS attribute says they have at least one underground floor, and then
uses the cheaper of two API query strategies for each legal dong:

* download every title row in the dong, or
* query only the candidate parcels in that dong.

The title result is used to find buildings that have both an underground floor
and indoor parking.  Floor-detail rows are then collected for those probable
underground-parking parcels and used to confirm that a basement floor's use
contains the Korean word for parking ("주차장").

Secrets and large raw/processed outputs are intentionally gitignored.  The
small manifest and sample in outputs/ are safe to commit.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import mmap
import os
import struct
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

from data_paths import (
    INTERIM_BUILDING_REGISTER,
    RAW_BUILDING_REGISTER,
    RAW_VWORLD_GYEONGBUK,
    ROOT,
)

RAW_DIR = RAW_BUILDING_REGISTER
PROCESSED_DIR = INTERIM_BUILDING_REGISTER
OUTPUT_DIR = ROOT / "outputs/gyeongbuk-building-register"
ENV_FILE = ROOT / ".env"
API_BASE = "https://apis.data.go.kr/1613000/BldRgstHubService"
PAGE_SIZE = 100  # The service caps larger requests at 100.

TITLE_RAW = RAW_DIR / "title_rows.jsonl"
TITLE_COMPLETED = RAW_DIR / "title_completed_tasks.txt"
TITLE_FAILURES = RAW_DIR / "title_failures.jsonl"
FLOOR_RAW = RAW_DIR / "floor_rows.jsonl"
FLOOR_COMPLETED = RAW_DIR / "floor_completed_groups.txt"
FLOOR_FAILURES = RAW_DIR / "floor_failures.jsonl"
TITLE_CSV = PROCESSED_DIR / "gyeongbuk_basement_candidate_titles.csv"
FLOOR_CSV = PROCESSED_DIR / "gyeongbuk_probable_parking_floors.csv"
COMBINED_CSV = PROCESSED_DIR / "gyeongbuk_underground_parking_candidates.csv"
GIS_CANDIDATE_CSV = PROCESSED_DIR / "gyeongbuk_gis_basement_candidates.csv"
MANIFEST = OUTPUT_DIR / "manifest.json"
SAMPLE = OUTPUT_DIR / "gyeongbuk_underground_parking_candidates_sample.csv"

TITLE_PREFERRED_FIELDS = [
    "pnu",
    "mgmBldrgstPk",
    "platPlc",
    "newPlatPlc",
    "sigunguCd",
    "bjdongCd",
    "platGbCd",
    "bun",
    "ji",
    "bldNm",
    "dongNm",
    "regstrGbCd",
    "regstrGbCdNm",
    "regstrKindCd",
    "regstrKindCdNm",
    "mainAtchGbCd",
    "mainAtchGbCdNm",
    "mainPurpsCd",
    "mainPurpsCdNm",
    "etcPurps",
    "ugrndFlrCnt",
    "grndFlrCnt",
    "indrMechUtcnt",
    "indrMechArea",
    "indrAutoUtcnt",
    "indrAutoArea",
    "oudrMechUtcnt",
    "oudrMechArea",
    "oudrAutoUtcnt",
    "oudrAutoArea",
    "useAprDay",
    "crtnDay",
]

FLOOR_PREFERRED_FIELDS = [
    "pnu",
    "mgmBldrgstPk",
    "platPlc",
    "newPlatPlc",
    "sigunguCd",
    "bjdongCd",
    "platGbCd",
    "bun",
    "ji",
    "bldNm",
    "dongNm",
    "flrGbCd",
    "flrGbCdNm",
    "flrNo",
    "flrNoNm",
    "mainPurpsCd",
    "mainPurpsCdNm",
    "etcPurps",
    "area",
    "crtnDay",
]


class BudgetExceeded(RuntimeError):
    pass


class CallBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self._lock = threading.Lock()

    def take(self) -> None:
        with self._lock:
            if self.used >= self.limit:
                raise BudgetExceeded(f"API call budget exhausted ({self.limit})")
            self.used += 1


@dataclass(frozen=True)
class QueryTask:
    task_id: str
    code: str
    pnu: str | None = None


def ensure_dirs() -> None:
    for path in (RAW_DIR, PROCESSED_DIR, OUTPUT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_env_key() -> str:
    value = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not value and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATA_GO_KR_SERVICE_KEY="):
                value = line.split("=", 1)[1].strip()
                break
    if not value:
        raise RuntimeError(
            "DATA_GO_KR_SERVICE_KEY is missing. Put it in the gitignored .env file."
        )
    # The portal may show a percent-encoded or decoded key. urllib.urlencode
    # expects the decoded value and will safely encode it once.
    return unquote(value)


def latest_gis_dbf_dir() -> Path:
    roots = {
        path
        for pattern in ("AL_D010_47_*", "AL_47_D010_*")
        for path in RAW_VWORLD_GYEONGBUK.glob(pattern)
        if path.is_dir() and any(path.glob("*.dbf"))
    }
    if not roots:
        raise FileNotFoundError(
            f"No Gyeongbuk GIS-building DBF directory found under {RAW_VWORLD_GYEONGBUK}"
        )
    return max(roots, key=lambda path: path.name.rsplit("_", 1)[-1])


def dbf_layout(path: Path) -> tuple[int, int, int, dict[str, tuple[int, int]]]:
    with path.open("rb") as stream:
        header = stream.read(32)
        row_count = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]
        fields: dict[str, tuple[int, int]] = {}
        offset = 1  # deletion marker
        while True:
            descriptor = stream.read(32)
            if not descriptor or descriptor[0] == 0x0D:
                break
            name = descriptor[:11].split(b"\0", 1)[0].decode("ascii")
            length = descriptor[16]
            fields[name] = (offset, length)
            offset += length
    required = {"A1", "A2", "A3", "A4", "A5", "A8", "A9", "A19", "A24", "A25", "A26", "A27"}
    missing = sorted(required - fields.keys())
    if missing:
        raise RuntimeError(f"{path.name} is missing expected fields: {missing}")
    return row_count, header_length, record_length, fields


def read_gis_inventory(dbf_dir: Path) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, set[str]]]:
    candidates: list[dict[str, Any]] = []
    all_rows_by_code: Counter[str] = Counter()
    candidate_pnus_by_code: dict[str, set[str]] = defaultdict(set)

    for path in sorted(dbf_dir.glob("*.dbf")):
        row_count, header_length, record_length, fields = dbf_layout(path)
        with path.open("rb") as stream:
            mm = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                for index in range(row_count):
                    start = header_length + index * record_length
                    if mm[start : start + 1] == b"*":
                        continue

                    def raw(name: str) -> bytes:
                        offset, length = fields[name]
                        return mm[start + offset : start + offset + length]

                    def ascii_value(name: str) -> str:
                        return raw(name).decode("ascii", "ignore").replace("\x00", "").strip()

                    def korean_value(name: str) -> str:
                        return raw(name).decode("cp949", "ignore").replace("\x00", "").strip()

                    code = ascii_value("A3")
                    if len(code) != 10 or not code.startswith("47") or not code.isdigit():
                        continue
                    all_rows_by_code[code] += 1
                    underground_floors = number(ascii_value("A27"))
                    if underground_floors <= 0:
                        continue
                    pnu = ascii_value("A2")
                    if len(pnu) == 19 and pnu.isdigit():
                        candidate_pnus_by_code[code].add(pnu)
                    candidates.append(
                        {
                            "gis_building_id": ascii_value("A1"),
                            "pnu": pnu,
                            "legal_dong_code": code,
                            "legal_dong_name": korean_value("A4"),
                            "lot_number": korean_value("A5"),
                            "building_use_code": ascii_value("A8"),
                            "building_use_name": korean_value("A9"),
                            "building_register_link_id": ascii_value("A19"),
                            "building_name": korean_value("A24"),
                            "dong_name": korean_value("A25"),
                            "ground_floor_count_gis": integer_or_none(ascii_value("A26")),
                            "underground_floor_count_gis": integer_or_none(ascii_value("A27")),
                            "source_dbf": path.name,
                        }
                    )
            finally:
                mm.close()
    return candidates, dict(all_rows_by_code), candidate_pnus_by_code


def number(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def integer_or_none(value: Any) -> int | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def write_csv(path: Path, rows: list[dict[str, Any]], preferred: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    all_fields = {key for row in rows for key in row}
    fields: list[str] = []
    if preferred:
        fields.extend(field for field in preferred if field in all_fields)
    fields.extend(sorted(all_fields - set(fields)))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if not fields:
            return
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(
            {
                key: value.replace("\x00", "").strip()
                if isinstance(value, str)
                else value
                for key, value in row.items()
            }
            for row in rows
        )


def row_pnu(row: dict[str, Any]) -> str | None:
    sigungu = str(row.get("sigunguCd") or "").strip().zfill(5)
    bjdong = str(row.get("bjdongCd") or "").strip().zfill(5)
    plat = str(row.get("platGbCd") or "").strip()
    bun = str(row.get("bun") or "").strip().zfill(4)
    ji = str(row.get("ji") or "").strip().zfill(4)
    pnu_land = {"0": "1", "1": "2"}.get(plat)
    if len(sigungu) != 5 or len(bjdong) != 5 or pnu_land is None:
        return None
    return f"{sigungu}{bjdong}{pnu_land}{bun}{ji}"


def pnu_params(pnu: str) -> dict[str, str]:
    if len(pnu) != 19 or not pnu.isdigit():
        raise ValueError(f"Invalid PNU: {pnu}")
    plat = {"1": "0", "2": "1"}.get(pnu[10])
    if plat is None:
        raise ValueError(f"Unsupported PNU land category: {pnu}")
    return {
        "sigunguCd": pnu[:5],
        "bjdongCd": pnu[5:10],
        "platGbCd": plat,
        "bun": pnu[11:15],
        "ji": pnu[15:19],
    }


class ApiClient:
    def __init__(self, endpoint: str, key: str, budget: CallBudget) -> None:
        self.endpoint = endpoint
        self.key = key
        self.budget = budget
        self.min_interval = float(os.environ.get("WATERPARK_API_MIN_INTERVAL", "0.35"))
        self._rate_lock = threading.Lock()
        self._next_request_at = 0.0
        self._cooldown_until = 0.0

    def wait_for_rate_limit(self) -> None:
        # All worker threads share one client, so this serializes request start
        # times without preventing response parsing from running concurrently.
        with self._rate_lock:
            now = time.monotonic()
            ready_at = max(self._next_request_at, self._cooldown_until)
            if ready_at > now:
                time.sleep(ready_at - now)
            self._next_request_at = time.monotonic() + self.min_interval

    def apply_cooldown(self, seconds: float) -> None:
        with self._rate_lock:
            self._cooldown_until = max(
                self._cooldown_until, time.monotonic() + seconds
            )

    def page(self, params: dict[str, str], page_no: int) -> tuple[list[dict[str, Any]], int]:
        query_params = {
            "serviceKey": self.key,
            **params,
            "_type": "json",
            "numOfRows": str(PAGE_SIZE),
            "pageNo": str(page_no),
        }
        last_error: Exception | None = None
        for attempt in range(7):
            self.wait_for_rate_limit()
            self.budget.take()
            request = Request(
                f"{API_BASE}/{self.endpoint}?{urlencode(query_params)}",
                headers={"User-Agent": "Waterpark-Hackathon/0.1"},
            )
            try:
                with urlopen(request, timeout=45) as response:
                    payload = response.read().decode("utf-8")
                document = json.loads(payload)
                response_doc = document.get("response") or {}
                header = response_doc.get("header") or {}
                if str(header.get("resultCode")) != "00":
                    raise RuntimeError(f"API error: {header}")
                body = response_doc.get("body") or {}
                items_doc = body.get("items") or {}
                items = items_doc.get("item") if isinstance(items_doc, dict) else []
                if isinstance(items, dict):
                    rows = [items]
                elif isinstance(items, list):
                    rows = items
                else:
                    rows = []
                return rows, int(body.get("totalCount") or 0)
            except BudgetExceeded:
                raise
            except HTTPError as exc:
                # HTTPError.__str__ may contain the full request URL, including
                # serviceKey. Keep failure logs useful without persisting it.
                last_error = RuntimeError(f"HTTP {exc.code}: {exc.reason}")
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    try:
                        cooldown = float(retry_after) if retry_after else 10.0 * (attempt + 1)
                    except ValueError:
                        cooldown = 10.0 * (attempt + 1)
                    self.apply_cooldown(min(60.0, cooldown))
                if attempt == 6:
                    break
                time.sleep(min(10.0, 0.5 * (2**attempt)))
            except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                if attempt == 6:
                    break
                time.sleep(min(10.0, 0.5 * (2**attempt)))
        raise RuntimeError(f"{self.endpoint} failed after retries: {last_error}")

    def all_pages(self, params: dict[str, str]) -> tuple[list[dict[str, Any]], int]:
        rows, total = self.page(params, 1)
        pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1
        for page_no in range(2, pages + 1):
            page_rows, _ = self.page(params, page_no)
            rows.extend(page_rows)
        return rows, total


def task_params(task: QueryTask) -> dict[str, str]:
    if task.pnu:
        return pnu_params(task.pnu)
    return {"sigunguCd": task.code[:5], "bjdongCd": task.code[5:]}


def load_completed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_line(path: Path, value: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(value + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def title_tasks(
    all_rows_by_code: dict[str, int], candidate_pnus_by_code: dict[str, set[str]]
) -> list[QueryTask]:
    tasks: list[QueryTask] = []
    for code in sorted(candidate_pnus_by_code):
        pnus = sorted(candidate_pnus_by_code[code])
        whole_dong_pages_estimate = math.ceil(all_rows_by_code.get(code, 0) / PAGE_SIZE)
        if whole_dong_pages_estimate <= len(pnus):
            tasks.append(QueryTask(f"whole:{code}", code))
        else:
            tasks.extend(QueryTask(f"parcel:{pnu}", code, pnu) for pnu in pnus)
    return tasks


def collect_titles(
    tasks: list[QueryTask], candidate_pnus: set[str], workers: int, budget: CallBudget
) -> dict[str, Any]:
    completed = load_completed(TITLE_COMPLETED)
    planned_task_ids = {task.task_id for task in tasks}
    pending = [task for task in tasks if task.task_id not in completed]
    client = ApiClient("getBrTitleInfo", load_env_key(), budget)
    failures: list[dict[str, str]] = []
    started = time.time()
    calls_at_start = budget.used

    def run(task: QueryTask) -> tuple[QueryTask, list[dict[str, Any]], int]:
        rows, total = client.all_pages(task_params(task))
        selected = []
        for row in rows:
            pnu = row_pnu(row)
            if pnu in candidate_pnus:
                row = dict(row)
                row["pnu"] = pnu
                selected.append(row)
        return task, selected, total

    print(
        json.dumps(
            {
                "stage": "titles",
                "planned_tasks": len(tasks),
                "already_completed": len(completed & planned_task_ids),
                "pending_tasks": len(pending),
                "shared_call_budget": budget.limit,
                "shared_calls_already_used": budget.used,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(run, task): task for task in pending}
        for index, future in enumerate(as_completed(future_map), start=1):
            task = future_map[future]
            try:
                finished_task, rows, _ = future.result()
                append_jsonl(TITLE_RAW, rows)
                append_line(TITLE_COMPLETED, finished_task.task_id)
            except Exception as exc:  # checkpoint all successes; report failures
                failure = {"task_id": task.task_id, "error": str(exc)}
                failures.append(failure)
                append_jsonl(TITLE_FAILURES, [failure])
            if index % 100 == 0 or index == len(pending):
                print(
                    json.dumps(
                        {
                            "stage": "titles",
                            "finished_pending_tasks": index,
                            "pending_tasks": len(pending),
                            "api_calls": budget.used,
                            "failures": len(failures),
                            "elapsed_seconds": round(time.time() - started, 1),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    completed_after = load_completed(TITLE_COMPLETED)
    return {
        "planned_tasks": len(tasks),
        "completed_tasks": len(completed_after & planned_task_ids),
        "all_planned_tasks_completed": planned_task_ids <= completed_after,
        "api_calls_this_stage": budget.used - calls_at_start,
        "api_calls_total_run": budget.used,
        "shared_call_budget": budget.limit,
        "failures": failures[:100],
    }


def deduplicate_titles() -> tuple[list[dict[str, Any]], set[str], dict[str, set[str]]]:
    by_pk: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(TITLE_RAW):
        pk = str(row.get("mgmBldrgstPk") or "").strip()
        if not pk:
            pk = hashlib.sha256(
                json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
        by_pk[pk] = row
    rows = sorted(
        by_pk.values(),
        key=lambda row: (
            str(row.get("sigunguCd") or ""),
            str(row.get("bjdongCd") or ""),
            str(row.get("pnu") or ""),
            str(row.get("mgmBldrgstPk") or ""),
        ),
    )
    probable_pks: set[str] = set()
    probable_pnus_by_code: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        underground = number(row.get("ugrndFlrCnt"))
        indoor_parking = number(row.get("indrMechUtcnt")) + number(row.get("indrAutoUtcnt"))
        if underground > 0 and indoor_parking > 0:
            pk = str(row.get("mgmBldrgstPk") or "").strip()
            pnu = str(row.get("pnu") or "").strip()
            code = f"{str(row.get('sigunguCd') or '').zfill(5)}{str(row.get('bjdongCd') or '').zfill(5)}"
            if pk and len(pnu) == 19:
                probable_pks.add(pk)
                probable_pnus_by_code[code].add(pnu)
    write_csv(TITLE_CSV, rows, TITLE_PREFERRED_FIELDS)
    return rows, probable_pks, probable_pnus_by_code


def collect_floor_group(
    code: str,
    pnus: set[str],
    probable_pks: set[str],
    client: ApiClient,
) -> tuple[list[dict[str, Any]], str]:
    # One unfiltered probe tells us whether whole-dong pagination is cheaper
    # than one exact-parcel call per probable parcel.  The probe's first page
    # is reused if whole-dong mode wins.
    base_params = {"sigunguCd": code[:5], "bjdongCd": code[5:]}
    first_rows, total = client.page(base_params, 1)
    pages = max(1, math.ceil(total / PAGE_SIZE)) if total else 1
    selected: list[dict[str, Any]] = []

    def keep(rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            pk = str(row.get("mgmBldrgstPk") or "").strip()
            if pk in probable_pks:
                row = dict(row)
                row["pnu"] = row_pnu(row)
                selected.append(row)

    if pages <= len(pnus):
        keep(first_rows)
        for page_no in range(2, pages + 1):
            rows, _ = client.page(base_params, page_no)
            keep(rows)
        mode = "whole"
    else:
        for pnu in sorted(pnus):
            rows, _ = client.all_pages(pnu_params(pnu))
            keep(rows)
        mode = "parcel"
    return selected, mode


def collect_floors(
    probable_pks: set[str],
    probable_pnus_by_code: dict[str, set[str]],
    workers: int,
    budget: CallBudget,
) -> dict[str, Any]:
    completed = load_completed(FLOOR_COMPLETED)
    codes = sorted(probable_pnus_by_code)
    planned_codes = set(codes)
    pending = [code for code in codes if code not in completed]
    client = ApiClient("getBrFlrOulnInfo", load_env_key(), budget)
    failures: list[dict[str, str]] = []
    modes: Counter[str] = Counter()
    started = time.time()
    calls_at_start = budget.used

    def run(code: str) -> tuple[str, list[dict[str, Any]], str]:
        rows, mode = collect_floor_group(
            code, probable_pnus_by_code[code], probable_pks, client
        )
        return code, rows, mode

    print(
        json.dumps(
            {
                "stage": "floors",
                "probable_building_pks": len(probable_pks),
                "probable_parcels": sum(len(v) for v in probable_pnus_by_code.values()),
                "planned_code_groups": len(codes),
                "already_completed": len(completed & planned_codes),
                "pending_code_groups": len(pending),
                "shared_call_budget": budget.limit,
                "shared_calls_already_used": budget.used,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(run, code): code for code in pending}
        for index, future in enumerate(as_completed(future_map), start=1):
            code = future_map[future]
            try:
                finished_code, rows, mode = future.result()
                append_jsonl(FLOOR_RAW, rows)
                append_line(FLOOR_COMPLETED, finished_code)
                modes[mode] += 1
            except Exception as exc:
                failure = {"code": code, "error": str(exc)}
                failures.append(failure)
                append_jsonl(FLOOR_FAILURES, [failure])
            if index % 50 == 0 or index == len(pending):
                print(
                    json.dumps(
                        {
                            "stage": "floors",
                            "finished_pending_groups": index,
                            "pending_code_groups": len(pending),
                            "api_calls": budget.used,
                            "modes": dict(modes),
                            "failures": len(failures),
                            "elapsed_seconds": round(time.time() - started, 1),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    completed_after = load_completed(FLOOR_COMPLETED)
    return {
        "planned_code_groups": len(codes),
        "completed_code_groups": len(completed_after & planned_codes),
        "all_planned_code_groups_completed": planned_codes <= completed_after,
        "api_calls_this_stage": budget.used - calls_at_start,
        "api_calls_total_run": budget.used,
        "shared_call_budget": budget.limit,
        "query_modes": dict(modes),
        "failures": failures[:100],
    }


def deduplicate_floors() -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(FLOOR_RAW):
        identity = "|".join(
            str(row.get(field) or "")
            for field in (
                "mgmBldrgstPk",
                "flrGbCd",
                "flrNo",
                "flrNoNm",
                "mainPurpsCd",
                "mainPurpsCdNm",
                "etcPurps",
                "area",
            )
        )
        unique[identity] = row
    rows = sorted(
        unique.values(),
        key=lambda row: (
            str(row.get("mgmBldrgstPk") or ""),
            number(row.get("flrNo")),
            str(row.get("mainPurpsCdNm") or ""),
        ),
    )
    write_csv(FLOOR_CSV, rows, FLOOR_PREFERRED_FIELDS)
    return rows


def finalize(
    gis_candidates: list[dict[str, Any]],
    dbf_dir: Path,
    title_stats: dict[str, Any] | None = None,
    floor_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title_rows, probable_pks, probable_pnus_by_code = deduplicate_titles()
    floor_rows = deduplicate_floors()
    confirmed_pks: set[str] = set()
    floor_pks: set[str] = set()
    for row in floor_rows:
        pk = str(row.get("mgmBldrgstPk") or "").strip()
        if pk:
            floor_pks.add(pk)
        is_basement = str(row.get("flrGbCd") or "").strip() == "10"
        use_text = f"{row.get('mainPurpsCdNm') or ''} {row.get('etcPurps') or ''}"
        if pk and is_basement and number(row.get("area")) > 0 and "주차장" in use_text:
            confirmed_pks.add(pk)

    floor_completed_codes = load_completed(FLOOR_COMPLETED)
    combined: list[dict[str, Any]] = []
    for row in title_rows:
        pk = str(row.get("mgmBldrgstPk") or "").strip()
        code = f"{str(row.get('sigunguCd') or '').zfill(5)}{str(row.get('bjdongCd') or '').zfill(5)}"
        underground = number(row.get("ugrndFlrCnt"))
        indoor_parking = number(row.get("indrMechUtcnt")) + number(row.get("indrAutoUtcnt"))
        if pk in confirmed_pks:
            status = "CONFIRMED_BASEMENT_PARKING_USE"
            evidence = "층별개요 지하층(flrGbCd=10)의 용도에 주차장 포함"
        elif underground > 0 and indoor_parking > 0 and code in floor_completed_codes:
            status = "PROBABLE_NOT_CONFIRMED_IN_FLOOR_ROWS"
            evidence = "지하층과 옥내주차는 있으나 수집된 지하층 용도에서 주차장 미확인"
        elif underground > 0 and indoor_parking > 0:
            status = "PROBABLE_FLOOR_DETAIL_NOT_COLLECTED"
            evidence = "지하층과 옥내주차가 있으나 층별개요 수집 미완료"
        elif underground > 0:
            status = "UNDERGROUND_FLOOR_ONLY"
            evidence = "지하층은 있으나 옥내주차 근거 없음"
        else:
            status = "GIS_BASEMENT_CANDIDATE_NOT_CONFIRMED_BY_TITLE"
            evidence = "GIS에는 지하층이 있으나 건축물대장 표제부에서 확인되지 않음"
        output = dict(row)
        output.update(
            {
                "underground_parking_status": status,
                "underground_parking_evidence": evidence,
                "indoor_parking_count": indoor_parking,
                "floor_detail_rows_collected": pk in floor_pks,
            }
        )
        combined.append(output)

    combined.sort(
        key=lambda row: (
            str(row.get("underground_parking_status") or ""),
            str(row.get("sigunguCd") or ""),
            str(row.get("bjdongCd") or ""),
            str(row.get("pnu") or ""),
            str(row.get("mgmBldrgstPk") or ""),
        )
    )
    write_csv(COMBINED_CSV, combined, [
        "underground_parking_status",
        "underground_parking_evidence",
        "floor_detail_rows_collected",
        "indoor_parking_count",
        *TITLE_PREFERRED_FIELDS,
    ])
    write_csv(SAMPLE, combined[:500], [
        "underground_parking_status",
        "underground_parking_evidence",
        "floor_detail_rows_collected",
        "indoor_parking_count",
        *TITLE_PREFERRED_FIELDS,
    ])

    status_counts = Counter(
        str(row.get("underground_parking_status") or "") for row in combined
    )
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": {
            "building_hub_api": "https://www.data.go.kr/data/15134735/openapi.do",
            "gis_building_dbf_directory": str(dbf_dir.relative_to(ROOT)),
            "gis_reference_date": dbf_dir.name.rsplit("_", 1)[-1],
        },
        "scope": "경상북도 GIS건물통합정보에서 지하층 수가 1 이상인 건물 후보",
        "gis_basement_candidate_rows": len(gis_candidates),
        "gis_basement_candidate_unique_pnus": len(
            {str(row.get("pnu") or "") for row in gis_candidates if row.get("pnu")}
        ),
        "title_rows": len(title_rows),
        "probable_title_buildings": len(probable_pks),
        "probable_parcels": sum(len(value) for value in probable_pnus_by_code.values()),
        "floor_rows": len(floor_rows),
        "confirmed_buildings": len(confirmed_pks),
        "status_counts": dict(sorted(status_counts.items())),
        "title_collection": title_stats or {},
        "floor_collection": floor_stats or {},
        "large_local_outputs": [
            str(TITLE_CSV.relative_to(ROOT)),
            str(FLOOR_CSV.relative_to(ROOT)),
            str(COMBINED_CSV.relative_to(ROOT)),
        ],
        "committed_sample": str(SAMPLE.relative_to(ROOT)),
        "limitations": [
            "수집 범위는 GIS 원본에서 지하층 수가 1 이상인 건물 후보이며 경북의 모든 표제부가 아니다.",
            "옥내주차는 지하주차와 동일하지 않아 층별개요 지하층 용도로 별도 확인한다.",
            "층별개요에 주차장 표기가 없다는 이유만으로 지하주차장이 없다고 단정하지 않는다.",
            "건축물대장 API에는 위도·경도가 없으며 GIS Polygon과 PNU/주소로 연결해야 한다.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        nargs="?",
        choices=("inventory", "titles", "floors", "finalize", "all"),
        default="all",
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--call-budget", type=int, default=9700)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dirs()
    dbf_dir = latest_gis_dbf_dir()
    print(f"Reading GIS candidate inventory from {dbf_dir.relative_to(ROOT)}", flush=True)
    gis_candidates, all_rows_by_code, candidate_pnus_by_code = read_gis_inventory(dbf_dir)
    write_csv(
        GIS_CANDIDATE_CSV,
        gis_candidates,
        [
            "gis_building_id",
            "pnu",
            "legal_dong_code",
            "legal_dong_name",
            "lot_number",
            "building_use_code",
            "building_use_name",
            "building_register_link_id",
            "building_name",
            "dong_name",
            "ground_floor_count_gis",
            "underground_floor_count_gis",
            "source_dbf",
        ],
    )
    print(
        json.dumps(
            {
                "stage": "inventory",
                "gis_candidate_rows": len(gis_candidates),
                "unique_candidate_pnus": sum(len(value) for value in candidate_pnus_by_code.values()),
                "legal_dong_codes": len(candidate_pnus_by_code),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.stage == "inventory":
        finalize(gis_candidates, dbf_dir)
        return

    all_candidate_pnus = {
        pnu for values in candidate_pnus_by_code.values() for pnu in values
    }
    tasks = title_tasks(all_rows_by_code, candidate_pnus_by_code)
    shared_budget = CallBudget(args.call_budget)
    title_stats: dict[str, Any] | None = None
    floor_stats: dict[str, Any] | None = None

    if args.stage in ("titles", "all"):
        title_stats = collect_titles(
            tasks, all_candidate_pnus, args.workers, shared_budget
        )
        if not title_stats["all_planned_tasks_completed"]:
            print(json.dumps(title_stats, ensure_ascii=False, indent=2), file=sys.stderr)
            finalize(gis_candidates, dbf_dir, title_stats=title_stats)
            raise SystemExit(2)

    if title_stats is None:
        completed_title_tasks = load_completed(TITLE_COMPLETED)
        planned_title_task_ids = {task.task_id for task in tasks}
        title_stats = {
            "planned_tasks": len(planned_title_task_ids),
            "completed_tasks": len(completed_title_tasks & planned_title_task_ids),
            "all_planned_tasks_completed": planned_title_task_ids <= completed_title_tasks,
        }

    title_rows, probable_pks, probable_pnus_by_code = deduplicate_titles()
    print(
        json.dumps(
            {
                "stage": "title_summary",
                "title_rows": len(title_rows),
                "probable_building_pks": len(probable_pks),
                "probable_parcels": sum(len(v) for v in probable_pnus_by_code.values()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    if args.stage in ("floors", "all"):
        floor_stats = collect_floors(
            probable_pks,
            probable_pnus_by_code,
            args.workers,
            shared_budget,
        )
        if not floor_stats["all_planned_code_groups_completed"]:
            print(json.dumps(floor_stats, ensure_ascii=False, indent=2), file=sys.stderr)
            finalize(
                gis_candidates,
                dbf_dir,
                title_stats=title_stats,
                floor_stats=floor_stats,
            )
            raise SystemExit(2)

    if floor_stats is None:
        completed_floor_codes = load_completed(FLOOR_COMPLETED)
        planned_floor_codes = set(probable_pnus_by_code)
        floor_stats = {
            "planned_code_groups": len(planned_floor_codes),
            "completed_code_groups": len(completed_floor_codes & planned_floor_codes),
            "all_planned_code_groups_completed": planned_floor_codes <= completed_floor_codes,
        }

    manifest = finalize(
        gis_candidates,
        dbf_dir,
        title_stats=title_stats,
        floor_stats=floor_stats,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
