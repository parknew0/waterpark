#!/usr/bin/env python3
"""Build the Waterpark data catalog from files that actually exist locally.

This script uses only the Python standard library.  It reads CSV/JSON/JSONL,
DBF headers and ZIP central directories without extracting or modifying source
data.  Values that have not been verified are deliberately left blank instead
of being estimated.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data/catalog.csv"

FLOOD_SOURCE = (
    "https://portal.esrikr.com/arcgis/rest/services/Hosted/"
    "Flood_2002_2022/FeatureServer/0"
)
VWORLD_SOURCE = (
    "https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=NA&dsId=18"
)
BUILDING_HUB_SOURCE = "https://www.data.go.kr/data/15134735/openapi.do"
KMA_AWS_SOURCE = "https://apihub.kma.go.kr/apiList.do?seqApi=2&seqApiSub=239"
KMA_STATION_SOURCE = "https://data.kma.go.kr/tmeta/stn/selectStnList.do?pgmNo=123"
PARKING_SOURCE = "https://www.data.go.kr/data/15012896/standard.do"


@dataclass(frozen=True)
class Asset:
    dataset_id: str
    name: str
    stage: str
    domain: str
    scope: str
    reference_date: str
    path: str
    format: str
    measurement: str
    crs: str
    availability_status: str
    verification_status: str
    repository_policy: str
    license_status: str
    source_url: str
    derived_from: str = ""
    notes: str = ""
    row_count_override: int | None = None
    column_count_override: int | None = None
    member_count_override: int | None = None
    encoding: str = "utf-8-sig"


CATALOG_COLUMNS = [
    "dataset_id",
    "name",
    "stage",
    "domain",
    "scope",
    "reference_date",
    "path",
    "format",
    "row_count",
    "column_count",
    "member_count",
    "crs",
    "bytes",
    "availability_status",
    "verification_status",
    "repository_policy",
    "license_status",
    "source_url",
    "derived_from",
    "notes",
]


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def csv_metadata(path: Path, *, encoding: str = "utf-8-sig") -> tuple[int, int]:
    if path.suffix == ".gz":
        stream_context = gzip.open(
            path, mode="rt", encoding=encoding, errors="replace", newline=""
        )
    else:
        stream_context = path.open(
            mode="rt", encoding=encoding, errors="replace", newline=""
        )
    with stream_context as stream:
        reader = csv.reader(stream)
        header: list[str] = []
        for candidate in reader:
            if any(value.strip() for value in candidate):
                header = candidate
                break
        rows = sum(1 for row in reader if any(value.strip() for value in row))
    return rows, len(header)


def json_array_metadata(paths: Iterable[Path]) -> tuple[int, int]:
    rows = 0
    columns: set[str] = set()
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, list):
            raise ValueError(f"Expected a JSON array: {relative(path)}")
        rows += len(value)
        for item in value:
            if isinstance(item, dict):
                columns.update(str(key) for key in item)
    return rows, len(columns)


def jsonl_metadata(path: Path) -> tuple[int, int]:
    rows = 0
    columns: set[str] = set()
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not line.strip():
                continue
            rows += 1
            value = json.loads(line)
            if isinstance(value, dict):
                columns.update(str(key) for key in value)
    return rows, len(columns)


def dbf_header(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise ValueError(f"Truncated DBF header: {relative(path)}")
        rows = struct.unpack("<I", header[4:8])[0]
        columns = 0
        while True:
            descriptor = stream.read(32)
            if not descriptor or descriptor[0] == 0x0D:
                break
            columns += 1
    return rows, columns


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def asset_paths(asset: Asset) -> list[Path]:
    if "*" in asset.path or "[" in asset.path:
        return sorted(ROOT.glob(asset.path))
    return [ROOT / asset.path]


def measure(asset: Asset) -> tuple[str, str, int]:
    paths = asset_paths(asset)
    existing = [path for path in paths if path.exists()]
    if not existing:
        return "", "", 0

    size = sum(directory_bytes(path) if path.is_dir() else path.stat().st_size for path in existing)
    if asset.row_count_override is not None:
        rows = asset.row_count_override
        columns = asset.column_count_override or 0
        return str(rows), str(columns) if columns else "", size

    if asset.measurement == "csv":
        rows, columns = csv_metadata(existing[0], encoding=asset.encoding)
        return str(rows), str(columns), size
    if asset.measurement == "json-array-group":
        rows, columns = json_array_metadata(existing)
        return str(rows), str(columns), size
    if asset.measurement == "jsonl":
        rows, columns = jsonl_metadata(existing[0])
        return str(rows), str(columns), size
    if asset.measurement == "dbf-directory":
        dbfs = sorted(existing[0].glob("*.dbf"))
        values = [dbf_header(path) for path in dbfs]
        rows = sum(value[0] for value in values)
        column_counts = sorted({value[1] for value in values})
        columns = "/".join(str(value) for value in column_counts)
        return str(rows), columns, size
    if asset.measurement == "zip-members":
        with zipfile.ZipFile(existing[0]) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
        return "", str(len(members)), size
    if asset.measurement == "file":
        return "", "", size
    raise ValueError(f"Unknown measurement {asset.measurement!r} for {asset.dataset_id}")


def prj_crs(directory: Path) -> str:
    """Return the verified EPSG code encoded by the snapshot's PRJ files."""

    prj_files = sorted(directory.glob("*.prj"))
    if not prj_files:
        return "OPEN—PRJ missing"
    definitions = "\n".join(
        path.read_text(encoding="utf-8", errors="replace").upper()
        for path in prj_files
    )
    if 'AUTHORITY["EPSG","5186"]' in definitions or "KOREA_2000_CENTRAL_BELT_2010" in definitions:
        return "EPSG:5186 (PRJ 확인)"
    if 'AUTHORITY["EPSG","5174"]' in definitions or "KOREAN_1985" in definitions:
        return "EPSG:5174 (PRJ 확인)"
    return "OPEN—PRJ present but EPSG not identified"


def gyeongbuk_vworld_assets() -> list[Asset]:
    root = ROOT / "data/raw/vworld-buildings/gyeongbuk"
    assets: list[Asset] = []
    for directory in sorted(path for path in root.glob("AL*D010*") if path.is_dir()):
        match = re.search(r"(20\d{6})$", directory.name)
        if not match:
            continue
        compact_date = match.group(1)
        reference_date = f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:]}"
        assets.append(
            Asset(
                dataset_id=f"vworld_gyeongbuk_buildings_{compact_date}",
                name=f"VWorld GIS건물통합정보 경북 {reference_date}",
                stage="raw",
                domain="building",
                scope="경상북도",
                reference_date=reference_date,
                path=relative(directory),
                format="Shapefile 3-part bundle",
                measurement="dbf-directory",
                crs=prj_crs(directory),
                availability_status="READY_LOCAL_ONLY",
                verification_status="DBF_HEADERS_AND_PRJ_VERIFIED",
                repository_policy="LOCAL_ONLY_GITIGNORED",
                license_status="OPEN—원본 재배포 권리 확인 전 로컬 전용",
                source_url=VWORLD_SOURCE,
                notes=(
                    "행 수는 3개 DBF 헤더 합계다. 같은 basename의 SHP/SHX/DBF/PRJ/"
                    "CPG 또는 FIX를 한 묶음으로 취급한다. A1은 모든 연도에서 완전한 유일키가 아니다."
                ),
            )
        )
    return assets


def fixed_assets() -> list[Asset]:
    return [
        Asset(
            "flood_trace_korea_raw",
            "전국 침수흔적도 2002-2022",
            "raw",
            "flood",
            "전국 17개 시도",
            "2024-11-27",
            "data/raw/flood-trace/korea_flood_2002_2022.geojson",
            "GeoJSON",
            "file",
            "EPSG:4326 / CRS84",
            "READY_LOCAL_ONLY",
            "MANIFEST_HASH_COUNT_CRS_TOPOLOGY_VERIFIED",
            "LOCAL_ONLY_GITIGNORED; MANIFEST_TRACKED",
            "OPEN—행정안전부·Esri Korea 재사용 조건 재확인 필요",
            FLOOD_SOURCE,
            notes=(
                "38,003 Polygon/MultiPolygon, 16 source attributes. 원본 도형은 수정하지 않았고 "
                "self-intersection 22건은 manifest에 기록했다."
            ),
            row_count_override=38_003,
            column_count_override=16,
        ),
        Asset(
            "flood_trace_gyeongbuk_raw",
            "경상북도 침수흔적도 부분집합",
            "raw",
            "flood",
            "경상북도",
            "2024-11-27",
            "data/raw/flood-trace/gyeongbuk_flood_2002_2022.geojson",
            "GeoJSON",
            "file",
            "EPSG:4326 / CRS84",
            "READY",
            "NATIONAL_SUBSET_VERIFIED",
            "GIT_TRACKED",
            "OPEN—행정안전부·Esri Korea 재사용 조건 재확인 필요",
            FLOOD_SOURCE,
            "flood_trace_korea_raw",
            "전국 원본의 stdg_ctpv_cd=47 결과와 objectid·속성·도형이 일치한다.",
            1_402,
            16,
        ),
        Asset(
            "vworld_korea_buildings_20221203_archive",
            "VWorld GIS건물통합정보 전국 2022 묶음",
            "raw",
            "building",
            "전국 17개 시도",
            "2022-12-03",
            "data/raw/vworld-downloads/national/2022-12-03/vworld_gis_buildings_national_2022-12-03.zip",
            "ZIP containing 17 province ZIPs / 24 Shapefile parts",
            "file",
            "EPSG:5174 (24개 PRJ 확인)",
            "READY_LOCAL_ONLY_WITH_LIMITATIONS",
            "OUTER_CRC_INNER_DBF_PRJ_SCHEMA_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "CC BY 배지 표시는 확인; 원본 재배포·2차 배포 조건은 미확정, 로컬 전용",
            VWORLD_SOURCE,
            notes=(
                "1,548,576,788 bytes; SHA-256 "
                "4bd30f10312bb7914e412c516e19c7e41f1ab049a09961b1d4d8c36bf354194d. "
                "17개 시도 ZIP, 24개 SHP part. 13,885,793은 DBF 헤더의 행 수 합계이며 "
                "deleted-record flag, A1 공백·중복, geometry 유효성·topology는 미검증이다. "
                "2022 스키마는 A0~A22까지만 있어 지하층수 A27이 없다. "
                "원본 geometry는 영구 추출하지 않았다."
            ),
            row_count_override=13_885_793,
            column_count_override=23,
            member_count_override=17,
        ),
        Asset(
            "vworld_korea_buildings_20221203_inventory",
            "VWorld GIS건물통합정보 전국 2022 SHP part 인벤토리",
            "interim",
            "building-qa",
            "전국 17개 시도",
            "2022-12-03",
            "data/interim/vworld-buildings/national_2022-12-03_inventory.csv",
            "CSV",
            "csv",
            "N/A (CRS는 행 단위 필드; 모두 EPSG:5174)",
            "READY",
            "OUTER_CRC_INNER_DBF_PRJ_SCHEMA_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "원본과 동일한 이용조건 적용; 원본 재배포 조건 미확정",
            VWORLD_SOURCE,
            "vworld_korea_buildings_20221203_archive",
            "24개 SHP part의 DBF 행·필드, PRJ, 사이드카 존재를 기록한 QA 표다.",
        ),
        Asset(
            "vworld_korea_buildings_20221203_fields",
            "VWorld GIS건물통합정보 전국 2022 필드 사전",
            "interim",
            "building-qa",
            "전국 2022 공통 스키마",
            "2022-12-03",
            "data/interim/vworld-buildings/national_2022-12-03_field_dictionary.csv",
            "CSV",
            "csv",
            "N/A",
            "READY",
            "OFFICIAL_DICTIONARY_AND_DBF_SCHEMA_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "VWorld 컬럼 정의서 이용조건 적용",
            VWORLD_SOURCE,
            "vworld_korea_buildings_20221203_archive",
            "A0~A22의 공식 한글명·실제 DBF 타입·길이와 후보 역할을 정리했다. "
            "A26 지상층수와 A27 지하층수는 이 2022 스냅샷에 없다.",
        ),
        Asset(
            "vworld_column_dictionary_20260102_raw",
            "VWorld 국가중점데이터 컬럼 정의서",
            "raw",
            "metadata",
            "VWorld 국가중점데이터",
            "2026-01-02",
            "data/raw/vworld-downloads/reference/vworld_national_core_data_column_dictionary_2026-01-02.xlsx",
            "XLSX",
            "file",
            "N/A",
            "READY_LOCAL_ONLY",
            "XLSX_CONTAINER_AND_SHA256_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "VWorld 이용조건 적용",
            VWORLD_SOURCE,
            notes=(
                "SHA-256 46dd29c6ab681c1e34cf00d91f8f2fe68b7e1868a853315eaa292838238ecb0f. "
                "AL_D010 공식 컬럼 정의는 워크북 773~801행에서 확인했다."
            ),
        ),
        Asset(
            "building_hub_title_raw",
            "건축HUB 표제부 원응답",
            "raw",
            "building",
            "경북 GIS 지하층 후보 범위",
            "2026-08-22",
            "data/raw/building-register/title_rows.jsonl",
            "JSONL",
            "jsonl",
            "N/A",
            "READY_LOCAL_ONLY",
            "JSONL_PARSE_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "공공데이터포털 이용허락 제한 없음 표기; 원응답 재배포는 별도 확인",
            BUILDING_HUB_SOURCE,
        ),
        Asset(
            "building_hub_floor_raw",
            "건축HUB 층별개요 원응답",
            "raw",
            "building",
            "경북 지하주차장 후보 범위",
            "2026-08-22",
            "data/raw/building-register/floor_rows.jsonl",
            "JSONL",
            "jsonl",
            "N/A",
            "READY_LOCAL_ONLY",
            "JSONL_PARSE_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "공공데이터포털 이용허락 제한 없음 표기; 원응답 재배포는 별도 확인",
            BUILDING_HUB_SOURCE,
        ),
        Asset(
            "building_hub_floor_failures",
            "건축HUB 층별개요 호출 실패 로그",
            "run-log",
            "building",
            "경북 지하주차장 후보 범위",
            "2026-08-22",
            "data/raw/building-register/floor_failures.jsonl",
            "JSONL",
            "jsonl",
            "N/A",
            "RUN_LOG_NOT_TRAINING_DATA",
            "JSONL_PARSE_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "N/A",
            BUILDING_HUB_SOURCE,
            notes="재시도 후 성공한 항목이 포함될 수 있어 미수집 행 수로 해석하지 않는다.",
        ),
        Asset(
            "kma_event_hourly_rain_raw",
            "경북 침수사건 KMA 시간강수 원응답",
            "raw",
            "rainfall",
            "전국 관측소 × 경북 사건시각",
            "2026-08-22",
            "data/raw/kma-rain/gyeongbuk_flood_event_hourly_rain_raw.jsonl",
            "JSONL",
            "jsonl",
            "N/A (관측소 좌표는 별도 목록)",
            "READY_LOCAL_ONLY",
            "JSONL_PARSE_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "기상청 자료 이용조건 재확인 필요",
            KMA_AWS_SOURCE,
        ),
        Asset(
            "kma_station_list_raw",
            "기상청 관측지점정보 원본",
            "raw",
            "station",
            "국내외 관측지점 이력",
            "2026-08-22",
            "data/raw/kma-stations/kma_station_list_raw.csv",
            "CSV (source encoding)",
            "csv",
            "EPSG:4326 좌표 컬럼",
            "READY_LOCAL_ONLY",
            "ROW_SCHEMA_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "기상청 자료 이용조건 재확인 필요",
            KMA_STATION_SOURCE,
            encoding="cp949",
        ),
        Asset(
            "kma_station_list_utf8",
            "기상청 관측지점정보 UTF-8 변환본",
            "interim",
            "station",
            "국내외 관측지점 이력",
            "2026-08-22",
            "data/raw/kma-stations/kma_station_list.csv",
            "CSV UTF-8",
            "csv",
            "EPSG:4326 좌표 컬럼",
            "READY",
            "ROW_SCHEMA_VERIFIED",
            "GIT_TRACKED",
            "기상청 자료 이용조건 재확인 필요",
            KMA_STATION_SOURCE,
            "kma_station_list_raw",
            "내용은 중간 변환본이지만 현재 경로는 raw 아래다.",
        ),
        Asset(
            "parking_standard_raw",
            "전국주차장정보표준데이터 원본 페이지",
            "raw",
            "parking",
            "전국",
            "2026-08-22 다운로드",
            "data/raw/parking_standard_page_*.json",
            "JSON array (2 pages)",
            "json-array-group",
            "EPSG:4326 좌표 컬럼",
            "READY",
            "ROW_SCHEMA_VERIFIED",
            "GIT_TRACKED",
            "공공데이터포털 표준데이터 이용조건 확인 필요",
            PARKING_SOURCE,
        ),
        Asset(
            "flood_trace_korea_records",
            "전국 침수흔적 속성표",
            "interim",
            "flood",
            "전국 17개 시도",
            "2024-11-27",
            "data/interim/flood-trace/korea_flood_records.csv",
            "CSV",
            "csv",
            "N/A (geometry excluded)",
            "READY_WITH_LIMITATIONS",
            "COUNT_SCHEMA_SOURCE_HASH_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "OPEN—원본과 동일한 재사용·재배포 조건 확인 필요",
            FLOOD_SOURCE,
            "flood_trace_korea_raw",
            "source attribute 16개만 보존하며 event_id는 만들지 않았다. 전체 속성 재배포 조건 확인 전 로컬 전용이다.",
        ),
        Asset(
            "flood_trace_korea_qa_province",
            "전국 침수흔적 시도별 QA",
            "interim",
            "flood-qa",
            "전국 17개 시도",
            "2024-11-27",
            "data/interim/flood-trace/korea_flood_qa_by_province.csv",
            "CSV",
            "csv",
            "N/A",
            "READY",
            "COUNT_AND_HASH_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "원본과 동일한 재사용 조건 적용",
            FLOOD_SOURCE,
            "flood_trace_korea_raw",
        ),
        Asset(
            "flood_trace_korea_qa_year",
            "전국 침수흔적 연도별 QA",
            "interim",
            "flood-qa",
            "전국",
            "2024-11-27",
            "data/interim/flood-trace/korea_flood_qa_by_year.csv",
            "CSV",
            "csv",
            "N/A",
            "READY",
            "COUNT_AND_HASH_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "원본과 동일한 재사용 조건 적용",
            FLOOD_SOURCE,
            "flood_trace_korea_raw",
        ),
        Asset(
            "flood_trace_gyeongbuk_records",
            "경북 침수흔적 속성표",
            "interim",
            "flood",
            "경상북도",
            "2024-11-27",
            "data/interim/flood-trace/gyeongbuk/gyeongbuk_flood_records.csv",
            "CSV",
            "csv",
            "N/A (geometry excluded)",
            "READY",
            "ROW_SCHEMA_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "원본과 동일한 재사용 조건 적용",
            FLOOD_SOURCE,
            "flood_trace_gyeongbuk_raw",
        ),
        Asset(
            "flood_trace_gyeongbuk_event_candidates",
            "경북 침수 시작일시 조합",
            "interim",
            "flood",
            "경상북도",
            "2002-2021 관측 기록",
            "data/interim/flood-trace/gyeongbuk/gyeongbuk_flood_events.csv",
            "CSV",
            "csv",
            "N/A",
            "READY_WITH_LIMITATIONS",
            "ROW_SCHEMA_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "원본과 동일한 재사용 조건 적용",
            FLOOD_SOURCE,
            "flood_trace_gyeongbuk_raw",
            "30개 날짜·시각 조합이며 독립적인 호우 사건 30개로 확정한 값은 아니다.",
        ),
        Asset(
            "building_register_gis_candidates",
            "GIS 지하층 보유 건물 후보",
            "interim",
            "building",
            "경상북도",
            "2025-12-04",
            "data/interim/building-register/gyeongbuk_gis_basement_candidates.csv",
            "CSV",
            "csv",
            "N/A (이 표에는 geometry 없음)",
            "READY_LOCAL_ONLY",
            "ROW_SCHEMA_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "VWorld 원본 재배포 조건 확인 필요",
            VWORLD_SOURCE,
            "vworld_gyeongbuk_buildings_20251204",
        ),
        Asset(
            "building_register_titles",
            "경북 지하층 후보 건축물대장 표제부",
            "interim",
            "building",
            "경상북도 후보 범위",
            "2026-08-22",
            "data/interim/building-register/gyeongbuk_basement_candidate_titles.csv",
            "CSV",
            "csv",
            "N/A",
            "READY_LOCAL_ONLY",
            "ROW_SCHEMA_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "건축HUB 이용조건 적용",
            BUILDING_HUB_SOURCE,
            "building_hub_title_raw",
        ),
        Asset(
            "building_register_floors",
            "경북 지하주차장 후보 층별개요",
            "interim",
            "building",
            "경상북도 후보 범위",
            "2026-08-22",
            "data/interim/building-register/gyeongbuk_probable_parking_floors.csv",
            "CSV",
            "csv",
            "N/A",
            "READY_LOCAL_ONLY",
            "ROW_SCHEMA_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "건축HUB 이용조건 적용",
            BUILDING_HUB_SOURCE,
            "building_hub_floor_raw",
        ),
        Asset(
            "building_register_parking_candidates",
            "경북 지하주차장 판정 후보 통합표",
            "interim",
            "building",
            "경상북도 후보 범위",
            "2026-08-22",
            "data/interim/building-register/gyeongbuk_underground_parking_candidates.csv",
            "CSV",
            "csv",
            "N/A",
            "READY_LOCAL_ONLY",
            "ROW_SCHEMA_VERIFIED",
            "LOCAL_ONLY_GITIGNORED",
            "건축HUB·VWorld 이용조건 적용",
            BUILDING_HUB_SOURCE,
            "building_register_titles;building_register_floors",
        ),
        Asset(
            "gyeongbuk_building_parking_features",
            "경북 지하층 건물 공간·대장 특징표",
            "processed",
            "building",
            "경상북도",
            "2025-12-04 건물 기준",
            "data/processed/buildings/gyeongbuk_building_underground_parking_features.csv",
            "CSV",
            "csv",
            "EPSG:4326 좌표 컬럼",
            "READY_WITH_LIMITATIONS",
            "ROW_SCHEMA_COORDINATE_RANGE_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "건축HUB·VWorld 이용조건 적용",
            BUILDING_HUB_SOURCE,
            "building_register_parking_candidates;vworld_gyeongbuk_buildings_20251204",
            "한 행은 GIS 지하층 건물이다. 지하주차장 판정은 PNU 단위여서 같은 필지 건물이 같은 판정을 공유할 수 있다.",
        ),
        Asset(
            "gyeongbuk_overture_elevation_parquet",
            "경북 Overture 건물·Copernicus DSM 특징",
            "processed",
            "building-terrain",
            "경상북도",
            "Overture 2026-08-19 / DSM 2021",
            "data/processed/buildings/gyeongbuk_buildings_elevation.parquet",
            "Parquet with WKB geometry",
            "file",
            "EPSG:4326 WKB/좌표",
            "READY_WITH_LIMITATIONS",
            "MANIFEST_ROW_SCHEMA_HASH_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "Overture ODbL 1.0 및 Copernicus 조건 적용",
            "https://overturemaps.org/;https://registry.opendata.aws/copernicus-dem/",
            notes="305,058행, 30컬럼. 원본 Overture/DEM 타일은 현재 로컬에 없어 이 파일만으로 처음부터 재생성할 수 없다.",
            row_count_override=305_058,
            column_count_override=30,
        ),
        Asset(
            "gyeongbuk_overture_elevation_csv",
            "경북 Overture 건물·Copernicus DSM 특징(도형 제외)",
            "processed",
            "building-terrain",
            "경상북도",
            "Overture 2026-08-19 / DSM 2021",
            "data/processed/buildings/gyeongbuk_buildings_elevation.csv.gz",
            "CSV.GZ",
            "csv",
            "EPSG:4326 좌표 컬럼",
            "READY_WITH_LIMITATIONS",
            "ROW_SCHEMA_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "Overture ODbL 1.0 및 Copernicus 조건 적용",
            "https://overturemaps.org/;https://registry.opendata.aws/copernicus-dem/",
            "gyeongbuk_overture_elevation_parquet",
            "Parquet와 같은 논리 데이터이며 geometry_wkb만 제외한다.",
        ),
        Asset(
            "gyeongbuk_event_station_rain",
            "경북 침수 시작일시 × 관측소 강수 특징",
            "processed",
            "rainfall",
            "경북 사건시각 × 전국 관측소",
            "2026-08-22 생성",
            "data/processed/rainfall/gyeongbuk_flood_event_rain.csv",
            "CSV",
            "csv",
            "N/A (station_id로 좌표 결합)",
            "READY_WITH_LIMITATIONS",
            "ROW_SCHEMA_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "기상청 자료 이용조건 적용",
            KMA_AWS_SOURCE,
            "kma_event_hourly_rain_raw;flood_trace_gyeongbuk_event_candidates",
        ),
        Asset(
            "gyeongbuk_surface_flood_training",
            "경북 지표면 침수 학습표",
            "processed",
            "ml-training",
            "경상북도 조사영향권",
            "2002-2021 사건 기록",
            "data/processed/ml/training/gyeongbuk_flood_training_table.csv",
            "CSV",
            "csv",
            "EPSG:4326 좌표 컬럼",
            "READY_WITH_LIMITATIONS",
            "ROW_SCHEMA_AND_MANIFEST_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "모든 원천의 이용조건 적용",
            FLOOD_SOURCE,
            "flood_trace_gyeongbuk_raw;gyeongbuk_overture_elevation_csv;gyeongbuk_event_station_rain",
            "정답은 지하주차장 침수가 아니라 지표면 침수다. 음성은 1km 내 약한 pseudo-negative다.",
        ),
        Asset(
            "gyeongbuk_parking_risk",
            "경북 지하층 건물 규칙 기반 위험표",
            "processed",
            "ml-output",
            "경상북도 지하층 건물",
            "2026-08-22 생성",
            "data/processed/ml/predictions/gyeongbuk_underground_parking_risk.csv",
            "CSV",
            "csv",
            "EPSG:4326 좌표 컬럼",
            "READY_WITH_LIMITATIONS",
            "ROW_SCHEMA_AND_MANIFEST_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "모든 원천의 이용조건 적용",
            FLOOD_SOURCE,
            "gyeongbuk_building_parking_features;gyeongbuk_overture_elevation_csv;flood_trace_gyeongbuk_raw",
            "지하주차장 실제 침수 확률이 아니라 지형·과거 지표면 침수 기반 상시 위험도다.",
        ),
        Asset(
            "gyeongbuk_public_parking_seed",
            "경북 공영주차장 후보",
            "processed",
            "parking",
            "경상북도 22개 시군",
            "2026-08-22 생성",
            "data/processed/parking/gyeongbuk_parking_seed.csv",
            "CSV",
            "csv",
            "EPSG:4326 좌표 컬럼",
            "READY_WITH_LIMITATIONS",
            "ROW_SCHEMA_VERIFIED",
            "GIT_TRACKED_DERIVED",
            "공공데이터포털 원천 조건 적용",
            PARKING_SOURCE,
            "parking_standard_raw",
            "대피 가능한 안전 주차장으로 검증된 목록은 아니다.",
        ),
    ]


def main() -> None:
    assets = fixed_assets() + gyeongbuk_vworld_assets()
    rows: list[dict[str, str | int]] = []
    for asset in assets:
        row_count, column_count, size = measure(asset)
        member_count = (
            str(asset.member_count_override)
            if asset.member_count_override is not None
            else ""
        )
        if asset.measurement == "zip-members" and not member_count:
            member_count, column_count = column_count, ""
        row = {
            "dataset_id": asset.dataset_id,
            "name": asset.name,
            "stage": asset.stage,
            "domain": asset.domain,
            "scope": asset.scope,
            "reference_date": asset.reference_date,
            "path": asset.path,
            "format": asset.format,
            "row_count": row_count,
            "column_count": column_count,
            "member_count": member_count,
            "crs": asset.crs,
            "bytes": size,
            "availability_status": asset.availability_status if size else "MISSING",
            "verification_status": asset.verification_status if size else "NOT_AVAILABLE",
            "repository_policy": asset.repository_policy,
            "license_status": asset.license_status,
            "source_url": asset.source_url,
            "derived_from": asset.derived_from,
            "notes": asset.notes,
        }
        rows.append(row)

    rows.sort(key=lambda row: str(row["dataset_id"]))
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CATALOG_PATH.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CATALOG_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[done] {len(rows)} assets -> {relative(CATALOG_PATH)}")


if __name__ == "__main__":
    main()
