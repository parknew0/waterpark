#!/usr/bin/env python3
"""Inventory the nested nationwide VWorld GIS-building download.

VWorld's selected-download result is one outer ZIP containing 17 province ZIPs.
Each province ZIP contains one or more Shapefile parts.  This script does not
flatten or alter the source geometry.  It reads the ZIP central directories and
DBF headers to produce a small, reviewable inventory for preprocessing design.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import struct
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath

from data_paths import INTERIM_VWORLD_BUILDINGS, ROOT


DEFAULT_ARCHIVE = (
    ROOT
    / "data/raw/vworld-downloads/national/2022-12-03/"
    "vworld_gis_buildings_national_2022-12-03.zip"
)
DEFAULT_INVENTORY = INTERIM_VWORLD_BUILDINGS / "national_2022-12-03_inventory.csv"
DEFAULT_MANIFEST = INTERIM_VWORLD_BUILDINGS / "national_2022-12-03_manifest.json"
DEFAULT_FIELD_DICTIONARY = (
    INTERIM_VWORLD_BUILDINGS / "national_2022-12-03_field_dictionary.csv"
)
EXPECTED_PROVINCE_CODES = {
    "11", "26", "27", "28", "29", "30", "31", "36", "41",
    "42", "43", "44", "45", "46", "47", "48", "50",
}
CURRENT_CATALOG_TOTAL_ROWS = 14_422_486
SOURCE_URL = "https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?dataSetSeq=18"
COLUMN_DICTIONARY_URL = (
    "https://www.vworld.kr/contents/"
    "%EA%B5%AD%EA%B0%80%EC%A4%91%EC%A0%90%EB%8D%B0%EC%9D%B4%ED%84%B0_"
    "%EC%BB%AC%EB%9F%BC%EC%A0%95%EC%9D%98%EC%84%9C(26.01.02)_"
    "%EB%B0%B0%ED%8F%AC%EC%9A%A9.xlsx"
)
COLUMN_DICTIONARY_SHA256 = (
    "46dd29c6ab681c1e34cf00d91f8f2fe68b7e1868a853315eaa292838238ecb0f"
)
FIELD_ALIASES_2022 = {
    "A0": "원천도형ID",
    "A1": "GIS건물통합식별번호",
    "A2": "고유번호(PNU)",
    "A3": "법정동코드",
    "A4": "법정동명",
    "A5": "지번",
    "A6": "특수지코드",
    "A7": "특수지구분명",
    "A8": "건축물용도코드",
    "A9": "건축물용도명",
    "A10": "건축물구조코드",
    "A11": "건축물구조명",
    "A12": "건축물면적(㎡)",
    "A13": "사용승인일자",
    "A14": "연면적",
    "A15": "대지면적(㎡)",
    "A16": "높이(m)",
    "A17": "건폐율(%)",
    "A18": "용적율(%)",
    "A19": "건축물ID",
    "A20": "위반건축물여부",
    "A21": "참조체계연계키",
    "A22": "데이터기준일자",
}
FIELD_ROLES_2022 = {
    "A0": "source_id",
    "A1": "candidate_building_id",
    "A2": "parcel_join_key",
    "A3": "administrative_join_key",
    "A4": "address_attribute",
    "A5": "address_attribute",
    "A6": "address_attribute",
    "A7": "address_attribute",
    "A8": "candidate_feature",
    "A9": "candidate_feature",
    "A10": "candidate_feature",
    "A11": "candidate_feature",
    "A12": "candidate_feature",
    "A13": "candidate_feature_and_time_filter",
    "A14": "candidate_feature",
    "A15": "candidate_feature",
    "A16": "candidate_feature",
    "A17": "candidate_feature",
    "A18": "candidate_feature",
    "A19": "candidate_join_key",
    "A20": "quality_attribute",
    "A21": "candidate_join_key",
    "A22": "snapshot_quality_attribute",
}
FIELDS_ADDED_AFTER_2022 = {
    "A23": "원천시도시군구코드",
    "A24": "건물명",
    "A25": "건물동명",
    "A26": "지상층_수",
    "A27": "지하층_수",
    "A28": "데이터생성변경일자",
}


class InventoryError(RuntimeError):
    """Raised when the nested download does not have the expected structure."""


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_dbf_header(stream) -> tuple[int, int, int, list[dict[str, object]]]:
    header = stream.read(32)
    if len(header) != 32:
        raise InventoryError("DBF header is truncated")
    row_count = struct.unpack("<I", header[4:8])[0]
    header_length = struct.unpack("<H", header[8:10])[0]
    record_length = struct.unpack("<H", header[10:12])[0]
    fields: list[dict[str, object]] = []
    while True:
        descriptor = stream.read(32)
        if not descriptor:
            raise InventoryError("DBF field descriptors are truncated")
        if descriptor[0] == 0x0D:
            break
        name = descriptor[:11].split(b"\0", 1)[0].decode("ascii", errors="replace")
        fields.append(
            {
                "name": name,
                "type": chr(descriptor[11]),
                "length": int(descriptor[16]),
                "decimal_count": int(descriptor[17]),
            }
        )
    return row_count, header_length, record_length, fields


def province_code(member_name: str) -> str:
    name = PurePosixPath(member_name).name
    parts = name.removesuffix(".zip").split("_")
    if len(parts) < 4 or parts[0] != "AL" or not parts[1].isdigit():
        raise InventoryError(f"Unexpected province archive name: {member_name}")
    return parts[1]


def matching_sidecars(names: set[str], dbf_name: str) -> dict[str, str]:
    base = dbf_name.rsplit(".", 1)[0]
    found = {}
    lower_to_original = {name.lower(): name for name in names}
    for extension in ("shp", "shx", "prj", "cpg", "fix"):
        key = f"{base}.{extension}".lower()
        if key in lower_to_original:
            found[extension] = lower_to_original[key]
    return found


def infer_crs(prj_text: str) -> str:
    normalized = prj_text.upper()
    if "KOREA_2000_CENTRAL_BELT_2010" in normalized or "5186" in normalized:
        return "EPSG:5186"
    if "KOREAN_1985" in normalized or "5174" in normalized:
        return "EPSG:5174"
    return "UNKNOWN"


def inspect_archive(archive: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    province_archives: list[str] = []
    with zipfile.ZipFile(archive) as outer:
        corrupt_outer = outer.testzip()
        if corrupt_outer:
            raise InventoryError(f"Outer ZIP CRC failed at {corrupt_outer}")
        members = [info for info in outer.infolist() if not info.is_dir()]
        if len(members) != 17:
            raise InventoryError(f"Expected 17 province ZIPs, found {len(members)}")

        for outer_info in sorted(members, key=lambda item: item.filename):
            if not outer_info.filename.lower().endswith(".zip"):
                raise InventoryError(f"Outer member is not a ZIP: {outer_info.filename}")
            code = province_code(outer_info.filename)
            province_archives.append(outer_info.filename)

            # A seekable temporary file avoids holding the largest province ZIP
            # entirely in memory while still leaving the raw archive unchanged.
            with tempfile.TemporaryFile() as temporary:
                with outer.open(outer_info) as source:
                    shutil.copyfileobj(source, temporary, length=8 * 1024 * 1024)
                temporary.seek(0)
                with zipfile.ZipFile(temporary) as inner:
                    infos = {info.filename: info for info in inner.infolist() if not info.is_dir()}
                    names = set(infos)
                    dbf_names = sorted(name for name in names if name.lower().endswith(".dbf"))
                    if not dbf_names:
                        raise InventoryError(f"No DBF found inside {outer_info.filename}")
                    for part_index, dbf_name in enumerate(dbf_names, start=1):
                        sidecars = matching_sidecars(names, dbf_name)
                        missing = sorted({"shp", "shx", "prj"} - set(sidecars))
                        if missing:
                            raise InventoryError(
                                f"{outer_info.filename}:{dbf_name} misses {', '.join(missing)}"
                            )
                        with inner.open(dbf_name) as dbf_stream:
                            row_count, header_length, record_length, fields = parse_dbf_header(dbf_stream)
                        with inner.open(sidecars["prj"]) as prj_stream:
                            prj_text = prj_stream.read().decode("utf-8", errors="replace").strip()
                        shp_info = infos[sidecars["shp"]]
                        dbf_info = infos[dbf_name]
                        rows.append(
                            {
                                "snapshot_date": "2022-12-03",
                                "province_code": code,
                                "province_archive": PurePosixPath(outer_info.filename).name,
                                "part_index": part_index,
                                "dbf_member": dbf_name,
                                "row_count": row_count,
                                "field_count": len(fields),
                                "field_names": ";".join(str(field["name"]) for field in fields),
                                "field_schema_json": json.dumps(fields, ensure_ascii=False, separators=(",", ":")),
                                "crs": infer_crs(prj_text),
                                "dbf_uncompressed_bytes": dbf_info.file_size,
                                "shp_uncompressed_bytes": shp_info.file_size,
                                "dbf_header_bytes": header_length,
                                "dbf_record_bytes": record_length,
                                "sidecars": ";".join(sorted(sidecars)),
                            }
                        )

    codes = {province_code(name) for name in province_archives}
    if codes != EXPECTED_PROVINCE_CODES:
        raise InventoryError(
            f"Province-code mismatch: missing={sorted(EXPECTED_PROVINCE_CODES - codes)}, "
            f"extra={sorted(codes - EXPECTED_PROVINCE_CODES)}"
        )
    total_rows = sum(int(row["row_count"]) for row in rows)
    if total_rows <= 0:
        raise InventoryError("The nationwide snapshot contains no DBF rows")

    schema_counts = Counter(
        (str(row["field_names"]), str(row["crs"])) for row in rows
    )
    actual_fields = str(rows[0]["field_names"]).split(";")
    if actual_fields != list(FIELD_ALIASES_2022):
        raise InventoryError(
            f"Unexpected 2022 field order: expected {list(FIELD_ALIASES_2022)}, "
            f"found {actual_fields}"
        )
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "name": "VWorld GIS건물통합정보",
            "url": SOURCE_URL,
            "selected_reference_date": "2022-12-03",
            "selected_scope": "전국 17개 시도 전체데이터",
            "current_catalog_total_records_observed": CURRENT_CATALOG_TOTAL_ROWS,
            "offered_format_for_snapshot": "SHP",
            "csv_search_result_count": 0,
            "license_badge_observed": "CC BY",
            "license_review": "원본 배포·2차 제공 조건은 사용 전 재확인 필요",
            "column_dictionary_url": COLUMN_DICTIONARY_URL,
            "column_dictionary_sha256": COLUMN_DICTIONARY_SHA256,
        },
        "archive": {
            "path": relative(archive),
            "size_bytes": archive.stat().st_size,
            "sha256": sha256_file(archive),
            "outer_crc_checked": True,
            "province_archive_count": len(province_archives),
        },
        "inventory": {
            "part_count": len(rows),
            "row_count": total_rows,
            "province_codes": sorted(codes),
            "crs_counts_by_part": dict(Counter(str(row["crs"]) for row in rows)),
            "schema_variant_count": len(schema_counts),
            "field_count_values": sorted({int(row["field_count"]) for row in rows}),
            "field_names": actual_fields,
            "fields_not_present_in_2022": FIELDS_ADDED_AFTER_2022,
        },
        "raw_geometry_modified": False,
        "important_notes": [
            "행 수는 DBF 헤더 기준이며 삭제 표시 행 여부는 전처리에서 다시 확인한다.",
            "A1 단독값은 건물 기본키로 확정하지 않는다.",
            "SHP 도형은 CSV로 버리지 않고 공간 결합용 원본으로 유지한다.",
            "이 스냅샷은 2022년 건물 현황이며 2002~2021년 당시 존재 여부를 자동 보장하지 않는다.",
            "VWorld 화면의 14,422,486건은 현재 데이터셋 전체 안내값이며, 2022-12-03 스냅샷의 DBF 헤더 합계는 별도로 계산한다.",
            "2022 스냅샷은 A0~A22까지만 있어 지상층수(A26)와 지하층수(A27)가 없다. 전국 지하층 정보 원천으로 사용할 수 없다.",
        ],
    }
    return rows, manifest


def build_field_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    schemas = {str(row["field_schema_json"]) for row in rows}
    if len(schemas) != 1:
        raise InventoryError("Cannot build one field dictionary from multiple DBF schemas")
    dbf_fields = json.loads(schemas.pop())
    return [
        {
            "field_name": field["name"],
            "official_korean_name": FIELD_ALIASES_2022[field["name"]],
            "dbf_type": field["type"],
            "dbf_length": field["length"],
            "dbf_decimal_count": field["decimal_count"],
            "candidate_ml_role": FIELD_ROLES_2022[field["name"]],
            "available_in_2022_snapshot": True,
        }
        for field in dbf_fields
    ]


def write_outputs(
    rows: list[dict[str, object]],
    field_rows: list[dict[str, object]],
    manifest: dict[str, object],
    csv_path: Path,
    field_dictionary_path: Path,
    manifest_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with field_dictionary_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(field_rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(field_rows)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--field-dictionary", type=Path, default=DEFAULT_FIELD_DICTIONARY
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.archive.is_file():
        raise SystemExit(f"Missing local VWorld archive: {args.archive}")
    rows, manifest = inspect_archive(args.archive)
    field_rows = build_field_rows(rows)
    write_outputs(
        rows,
        field_rows,
        manifest,
        args.inventory,
        args.field_dictionary,
        args.manifest,
    )
    print(
        f"[check] {len(rows)} Shapefile parts, "
        f"{manifest['inventory']['row_count']:,} DBF rows, "
        f"{manifest['archive']['province_archive_count']} province ZIPs"
    )
    print(f"[check] wrote {relative(args.inventory)}")
    print(f"[check] wrote {relative(args.field_dictionary)}")
    print(f"[check] wrote {relative(args.manifest)}")


if __name__ == "__main__":
    main()
