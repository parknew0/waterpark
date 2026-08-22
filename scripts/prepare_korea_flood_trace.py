#!/usr/bin/env python3
"""Prepare nationwide flood-trace attributes for first-pass ML QA.

The raw GeoJSON remains the spatial source of truth.  This script writes a
geometry-free record table plus province/year QA summaries, without inventing
an ``event_id`` or changing any source attribute names.

Topology validation is intentionally not reimplemented here.  Instead, the
script verifies the downloader manifest against the raw file hash and carries
forward its topology result.  This makes the 22 known invalid raw geometries
visible without silently repairing or modifying them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from data_paths import INTERIM_FLOOD_TRACE, RAW_FLOOD_TRACE, ROOT

DEFAULT_INPUT = RAW_FLOOD_TRACE / "korea_flood_2002_2022.geojson"
DEFAULT_RAW_MANIFEST = RAW_FLOOD_TRACE / "korea_flood_2002_2022.manifest.json"
DEFAULT_OUTPUT_DIR = INTERIM_FLOOD_TRACE

EXPECTED_RECORD_COUNT = 38_003
EXPECTED_PROVINCE_CODES = {
    11,
    26,
    27,
    28,
    29,
    30,
    31,
    36,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    50,
}
EXPECTED_TOPOLOGY_INVALID_COUNT = 22
EXPECTED_TIME_QUALITY = {
    "fldn_bgng_tm": {"missing_count": 988, "literal_0000_count": 8_789},
    "fldn_end_tm": {"missing_count": 991, "literal_0000_count": 6_933},
}

RECORDS_FILENAME = "korea_flood_records.csv"
PROVINCE_QA_FILENAME = "korea_flood_qa_by_province.csv"
YEAR_QA_FILENAME = "korea_flood_qa_by_year.csv"
MANIFEST_FILENAME = "korea_flood_preprocessing_manifest.json"

GROUP_QA_COLUMNS = [
    "record_count",
    "unique_fldn_bgng_ymd_count",
    "missing_fldn_bgng_ymd_count",
    "missing_fldn_bgng_tm_count",
    "fldn_bgng_tm_0000_count",
    "fldn_bgng_tm_unavailable_count",
    "missing_fldn_end_ymd_count",
    "missing_fldn_end_tm_count",
    "fldn_end_tm_0000_count",
    "fldn_end_tm_unavailable_count",
    "topology_invalid_count",
]


class PreparationError(RuntimeError):
    """Raised when the fixed nationwide source snapshot fails validation."""


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError(f"Cannot read valid JSON from {display_path(path)}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreparationError(f"Expected a JSON object in {display_path(path)}")
    return value


def source_fields(raw_manifest: dict[str, Any]) -> list[str]:
    fields = raw_manifest.get("attribute_fields")
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(field, str) and field for field in fields)
        or len(fields) != len(set(fields))
    ):
        raise PreparationError("Raw manifest has no valid, unique attribute_fields list")
    if "event_id" in fields:
        raise PreparationError("The raw source unexpectedly contains event_id")
    return fields


def validate_raw_manifest(
    raw_manifest: dict[str, Any],
    *,
    input_path: Path,
) -> tuple[list[str], set[int], str]:
    fields = source_fields(raw_manifest)
    expected_hash = raw_manifest.get("output", {}).get("sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise PreparationError("Raw manifest has no valid output.sha256")
    actual_hash = sha256_file(input_path)
    if actual_hash != expected_hash:
        raise PreparationError(
            "Raw GeoJSON hash does not match its downloader manifest: "
            f"expected {expected_hash}, got {actual_hash}"
        )

    if raw_manifest.get("feature_count") != EXPECTED_RECORD_COUNT:
        raise PreparationError(
            "Raw manifest feature count changed: "
            f"expected {EXPECTED_RECORD_COUNT}, got {raw_manifest.get('feature_count')!r}"
        )

    topology = raw_manifest.get("geometry", {}).get("topology")
    if not isinstance(topology, dict) or topology.get("checked") is not True:
        raise PreparationError("Raw manifest does not contain a completed topology check")
    if topology.get("raw_geometry_modified") is not False:
        raise PreparationError("Raw manifest does not confirm that geometry was left unchanged")
    if topology.get("invalid_count") != EXPECTED_TOPOLOGY_INVALID_COUNT:
        raise PreparationError(
            "Known topology-invalid count changed: "
            f"expected {EXPECTED_TOPOLOGY_INVALID_COUNT}, got {topology.get('invalid_count')!r}"
        )

    invalid_features = topology.get("invalid_features")
    if not isinstance(invalid_features, list) or len(invalid_features) != EXPECTED_TOPOLOGY_INVALID_COUNT:
        raise PreparationError("Raw manifest topology invalid_features is incomplete")
    invalid_ids: list[int] = []
    for item in invalid_features:
        if not isinstance(item, dict) or not isinstance(item.get("objectid"), int):
            raise PreparationError("Raw manifest contains an invalid topology objectid")
        if not isinstance(item.get("reason"), str) or not item["reason"]:
            raise PreparationError("Raw manifest contains an invalid topology reason")
        invalid_ids.append(item["objectid"])
    if len(set(invalid_ids)) != EXPECTED_TOPOLOGY_INVALID_COUNT:
        raise PreparationError("Raw manifest contains duplicate topology-invalid object IDs")

    return fields, set(invalid_ids), actual_hash


def load_and_validate_features(
    input_path: Path,
    *,
    fields: list[str],
    topology_invalid_ids: set[int],
) -> list[dict[str, Any]]:
    source = load_json_object(input_path)
    if source.get("type") != "FeatureCollection":
        raise PreparationError("Raw input is not a GeoJSON FeatureCollection")
    raw_features = source.get("features")
    if not isinstance(raw_features, list) or len(raw_features) != EXPECTED_RECORD_COUNT:
        raise PreparationError(
            f"Expected {EXPECTED_RECORD_COUNT:,} features, got "
            f"{len(raw_features) if isinstance(raw_features, list) else type(raw_features).__name__}"
        )

    expected_field_set = set(fields)
    rows: list[dict[str, Any]] = []
    object_ids: set[int] = set()
    geometry_missing_count = 0
    for index, feature in enumerate(raw_features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise PreparationError(f"Feature index {index} is not a GeoJSON Feature")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise PreparationError(f"Feature index {index} has no properties object")
        if set(properties) != expected_field_set:
            raise PreparationError(
                f"Feature index {index} attribute schema differs from the raw manifest"
            )
        object_id = properties.get("objectid")
        if not isinstance(object_id, int) or object_id in object_ids:
            raise PreparationError(f"Invalid or duplicate objectid at feature index {index}: {object_id!r}")
        object_ids.add(object_id)

        geometry = feature.get("geometry")
        if geometry is None:
            geometry_missing_count += 1
        elif not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise PreparationError(f"Feature objectid={object_id} has invalid geometry metadata")

        # Build a new mapping in the source manifest's canonical field order.
        # No source attribute is renamed or derived in this records table.
        rows.append({field: properties[field] for field in fields})

    if geometry_missing_count:
        raise PreparationError(f"Raw input contains {geometry_missing_count} missing geometries")
    if not topology_invalid_ids.issubset(object_ids):
        missing_ids = sorted(topology_invalid_ids - object_ids)
        raise PreparationError(f"Topology-invalid object IDs are absent from the raw input: {missing_ids}")

    rows.sort(key=lambda row: row["objectid"])
    return rows


def time_quality(rows: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    missing_count = 0
    literal_zero_count = 0
    for row in rows:
        value = row[field]
        missing_count += int(is_missing(value))
        literal_zero_count += int(value == "0000")
    return {
        "missing_count": missing_count,
        "literal_0000_count": literal_zero_count,
        "unavailable_count": missing_count + literal_zero_count,
    }


def empty_group_stats() -> dict[str, Any]:
    return {
        "record_count": 0,
        "start_dates": set(),
        "missing_fldn_bgng_ymd_count": 0,
        "missing_fldn_bgng_tm_count": 0,
        "fldn_bgng_tm_0000_count": 0,
        "missing_fldn_end_ymd_count": 0,
        "missing_fldn_end_tm_count": 0,
        "fldn_end_tm_0000_count": 0,
        "topology_invalid_count": 0,
        "province_codes": set(),
    }


def add_to_group(
    stats: dict[str, Any],
    row: dict[str, Any],
    *,
    topology_invalid_ids: set[int],
) -> None:
    stats["record_count"] += 1
    if not is_missing(row["fldn_bgng_ymd"]):
        stats["start_dates"].add(row["fldn_bgng_ymd"])
    stats["missing_fldn_bgng_ymd_count"] += int(is_missing(row["fldn_bgng_ymd"]))
    stats["missing_fldn_bgng_tm_count"] += int(is_missing(row["fldn_bgng_tm"]))
    stats["fldn_bgng_tm_0000_count"] += int(row["fldn_bgng_tm"] == "0000")
    stats["missing_fldn_end_ymd_count"] += int(is_missing(row["fldn_end_ymd"]))
    stats["missing_fldn_end_tm_count"] += int(is_missing(row["fldn_end_tm"]))
    stats["fldn_end_tm_0000_count"] += int(row["fldn_end_tm"] == "0000")
    stats["topology_invalid_count"] += int(row["objectid"] in topology_invalid_ids)
    stats["province_codes"].add(row["stdg_ctpv_cd"])


def finish_group_stats(stats: dict[str, Any]) -> dict[str, int]:
    return {
        "record_count": stats["record_count"],
        "unique_fldn_bgng_ymd_count": len(stats["start_dates"]),
        "missing_fldn_bgng_ymd_count": stats["missing_fldn_bgng_ymd_count"],
        "missing_fldn_bgng_tm_count": stats["missing_fldn_bgng_tm_count"],
        "fldn_bgng_tm_0000_count": stats["fldn_bgng_tm_0000_count"],
        "fldn_bgng_tm_unavailable_count": (
            stats["missing_fldn_bgng_tm_count"] + stats["fldn_bgng_tm_0000_count"]
        ),
        "missing_fldn_end_ymd_count": stats["missing_fldn_end_ymd_count"],
        "missing_fldn_end_tm_count": stats["missing_fldn_end_tm_count"],
        "fldn_end_tm_0000_count": stats["fldn_end_tm_0000_count"],
        "fldn_end_tm_unavailable_count": (
            stats["missing_fldn_end_tm_count"] + stats["fldn_end_tm_0000_count"]
        ),
        "topology_invalid_count": stats["topology_invalid_count"],
    }


def build_group_summaries(
    rows: list[dict[str, Any]],
    *,
    topology_invalid_ids: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    province_groups: dict[int, dict[str, Any]] = defaultdict(empty_group_stats)
    year_groups: dict[int, dict[str, Any]] = defaultdict(empty_group_stats)
    for row in rows:
        province = row["stdg_ctpv_cd"]
        year = row["fldn_yr"]
        if not isinstance(province, int):
            raise PreparationError(f"Non-integer stdg_ctpv_cd: {province!r}")
        if not isinstance(year, int):
            raise PreparationError(f"Non-integer fldn_yr: {year!r}")
        add_to_group(province_groups[province], row, topology_invalid_ids=topology_invalid_ids)
        add_to_group(year_groups[year], row, topology_invalid_ids=topology_invalid_ids)

    province_codes = set(province_groups)
    if province_codes != EXPECTED_PROVINCE_CODES:
        raise PreparationError(
            "Province-code coverage changed: "
            f"expected {sorted(EXPECTED_PROVINCE_CODES)}, got {sorted(province_codes)}"
        )

    province_rows: list[dict[str, Any]] = []
    for province in sorted(province_groups):
        province_rows.append(
            {"stdg_ctpv_cd": province, **finish_group_stats(province_groups[province])}
        )

    year_rows: list[dict[str, Any]] = []
    for year in sorted(year_groups):
        stats = year_groups[year]
        year_rows.append(
            {
                "fldn_yr": year,
                **finish_group_stats(stats),
                "province_count": len(stats["province_codes"]),
            }
        )

    if sum(row["record_count"] for row in province_rows) != EXPECTED_RECORD_COUNT:
        raise PreparationError("Province QA counts do not sum to the raw record count")
    if sum(row["record_count"] for row in year_rows) != EXPECTED_RECORD_COUNT:
        raise PreparationError("Year QA counts do not sum to the raw record count")
    if sum(row["topology_invalid_count"] for row in province_rows) != EXPECTED_TOPOLOGY_INVALID_COUNT:
        raise PreparationError("Province QA topology counts do not sum to 22")
    if sum(row["topology_invalid_count"] for row in year_rows) != EXPECTED_TOPOLOGY_INVALID_COUNT:
        raise PreparationError("Year QA topology counts do not sum to 22")

    return province_rows, year_rows


def temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp.{os.getpid()}")


def write_csv(path: Path, *, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def prepare(
    *,
    input_path: Path,
    raw_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if not input_path.is_file():
        raise PreparationError(f"Raw GeoJSON does not exist: {display_path(input_path)}")
    if not raw_manifest_path.is_file():
        raise PreparationError(
            f"Downloader manifest does not exist: {display_path(raw_manifest_path)}"
        )

    raw_manifest = load_json_object(raw_manifest_path)
    fields, topology_invalid_ids, input_hash = validate_raw_manifest(
        raw_manifest,
        input_path=input_path,
    )
    rows = load_and_validate_features(
        input_path,
        fields=fields,
        topology_invalid_ids=topology_invalid_ids,
    )
    if len(rows) != EXPECTED_RECORD_COUNT:
        raise PreparationError(f"Expected {EXPECTED_RECORD_COUNT:,} records, got {len(rows):,}")

    missing_count_by_field = {
        field: sum(int(is_missing(row[field])) for row in rows) for field in fields
    }
    time_quality_by_field = {
        field: time_quality(rows, field) for field in ("fldn_bgng_tm", "fldn_end_tm")
    }
    for field, expected in EXPECTED_TIME_QUALITY.items():
        actual = time_quality_by_field[field]
        for metric, expected_count in expected.items():
            if actual[metric] != expected_count:
                raise PreparationError(
                    f"{field} {metric} changed: expected {expected_count:,}, got {actual[metric]:,}"
                )

    province_rows, year_rows = build_group_summaries(
        rows,
        topology_invalid_ids=topology_invalid_ids,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    final_paths = {
        "records": output_dir / RECORDS_FILENAME,
        "qa_by_province": output_dir / PROVINCE_QA_FILENAME,
        "qa_by_year": output_dir / YEAR_QA_FILENAME,
        "manifest": output_dir / MANIFEST_FILENAME,
    }
    temp_paths = {name: temporary_path(path) for name, path in final_paths.items()}
    for path in temp_paths.values():
        if path.exists():
            path.unlink()

    try:
        write_csv(temp_paths["records"], fieldnames=fields, rows=rows)
        write_csv(
            temp_paths["qa_by_province"],
            fieldnames=["stdg_ctpv_cd", *GROUP_QA_COLUMNS],
            rows=province_rows,
        )
        write_csv(
            temp_paths["qa_by_year"],
            fieldnames=["fldn_yr", *GROUP_QA_COLUMNS, "province_count"],
            rows=year_rows,
        )

        manifest: dict[str, Any] = {
            "dataset": "전국 침수흔적도(2002-2022) 전처리 1단계",
            "script": display_path(Path(__file__)),
            "input": {
                "path": display_path(input_path),
                "sha256": input_hash,
                "raw_manifest_path": display_path(raw_manifest_path),
                "feature_count": len(rows),
                "attribute_fields": fields,
                "geometry_handling": (
                    "Geometry is intentionally excluded from the records CSV and remains "
                    "unchanged in the raw GeoJSON."
                ),
            },
            "outputs": {
                name: {
                    "path": display_path(final_paths[name]),
                    "sha256": sha256_file(temp_paths[name]),
                    "row_count": (
                        len(rows)
                        if name == "records"
                        else len(province_rows)
                        if name == "qa_by_province"
                        else len(year_rows)
                    ),
                }
                for name in ("records", "qa_by_province", "qa_by_year")
            },
            "validation": {
                "record_count": len(rows),
                "expected_record_count": EXPECTED_RECORD_COUNT,
                "objectid_unique_count": len({row["objectid"] for row in rows}),
                "province_count": len(province_rows),
                "expected_province_count": len(EXPECTED_PROVINCE_CODES),
                "province_codes": sorted(EXPECTED_PROVINCE_CODES),
                "year_value_count": len(year_rows),
                "year_values": [row["fldn_yr"] for row in year_rows],
                "missing_count_by_source_field": missing_count_by_field,
                "time_quality": time_quality_by_field,
                "topology": {
                    "validation_method": (
                        "Verified the downloader topology result against the raw GeoJSON SHA-256; "
                        "no geometry was repaired or modified."
                    ),
                    "checked": True,
                    "invalid_count": len(topology_invalid_ids),
                    "expected_invalid_count": EXPECTED_TOPOLOGY_INVALID_COUNT,
                    "invalid_objectids": sorted(topology_invalid_ids),
                    "raw_geometry_modified": False,
                },
                "event_id_created": False,
                "all_source_attribute_names_preserved": True,
            },
        }
        write_json(temp_paths["manifest"], manifest)

        # Each artifact is replaced atomically only after every validation and
        # every temporary output has been written successfully.
        for name in ("records", "qa_by_province", "qa_by_year", "manifest"):
            os.replace(temp_paths[name], final_paths[name])
    finally:
        for path in temp_paths.values():
            if path.exists():
                path.unlink()

    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--raw-manifest", type=Path, default=DEFAULT_RAW_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = prepare(
            input_path=args.input.resolve(),
            raw_manifest_path=args.raw_manifest.resolve(),
            output_dir=args.output_dir.resolve(),
        )
    except PreparationError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(
        "Prepared nationwide flood-trace attributes: "
        f"{manifest['validation']['record_count']:,} records, "
        f"{manifest['validation']['province_count']} provinces, "
        f"{manifest['validation']['topology']['invalid_count']} known topology-invalid geometries."
    )
    for output in manifest["outputs"].values():
        print(f"- {output['path']} ({output['row_count']:,} rows)")
    print(f"- {display_path(args.output_dir.resolve() / MANIFEST_FILENAME)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
