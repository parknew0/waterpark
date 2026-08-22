#!/usr/bin/env python3
"""Download and verify the nationwide 2002-2022 flood-trace polygons.

The source is the public Esri Korea mirror of the Ministry of the Interior and
Safety flood-trace layer.  ArcGIS caps a query response at 2,000 features, so
this script downloads stable ``objectid``-ordered pages and combines them into
one GeoJSON FeatureCollection.

Interrupted downloads resume from validated page files.  A completed download
is accepted only when its feature count, object IDs, attributes, geometries and
CRS all pass validation.  The source layer is stored in Web Mercator
(EPSG:3857); asking ArcGIS for ``outSR=4326`` produces RFC 7946-compatible
longitude/latitude GeoJSON for local spatial joins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from data_paths import RAW_FLOOD_TRACE, ROOT

RAW_DIR = RAW_FLOOD_TRACE
DEFAULT_OUTPUT = RAW_DIR / "korea_flood_2002_2022.geojson"
DEFAULT_MANIFEST = RAW_DIR / "korea_flood_2002_2022.manifest.json"
DEFAULT_PARTS_DIR = RAW_DIR / ".korea_flood_2002_2022.parts"
PARTS_SENTINEL_NAME = ".waterpark-flood-download-parts"

SERVICE_URL = (
    "https://portal.esrikr.com/arcgis/rest/services/Hosted/"
    "Flood_2002_2022/FeatureServer"
)
LAYER_URL = f"{SERVICE_URL}/0"
ITEM_URL = "https://www.arcgis.com/home/item.html?id=36b15209737c49b3893332c71db04a27"
ORIGINAL_APPROVAL_URL = "https://www.safetydata.go.kr/disaster-data/view?dataSn=108"
QUERY_URL = f"{LAYER_URL}/query"
EXPECTED_FEATURE_COUNT = 38_003
OUTPUT_EPSG = 4326
DEFAULT_PAGE_SIZE = 2_000
USER_AGENT = "Waterpark-data-collector/1.0"


class DownloadError(RuntimeError):
    """Raised when the source response or downloaded artifact is invalid."""


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 120.0,
    retries: int = 6,
) -> dict[str, Any]:
    if params:
        url = f"{url}?{urlencode(params)}"

    delay = 1.0
    for attempt in range(1, retries + 1):
        request = Request(
            url,
            headers={"Accept": "application/json, application/geo+json", "User-Agent": USER_AGENT},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise DownloadError(f"Expected a JSON object from {url}")
            if "error" in result:
                raise DownloadError(
                    f"ArcGIS returned an error from {url}: "
                    f"{json.dumps(result['error'], ensure_ascii=False)}"
                )
            return result
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in {
                408,
                429,
                500,
                502,
                503,
                504,
            }
            if attempt == retries or not retryable:
                raise DownloadError(f"Request failed after {attempt} attempt(s): {url}: {exc}") from exc
            print(
                f"[retry] attempt {attempt}/{retries} failed: {exc}; waiting {delay:.0f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay = min(delay * 2.0, 30.0)

    raise AssertionError("unreachable")


def atomic_write_json(path: Path, value: Any, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            value,
            stream,
            ensure_ascii=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=pretty,
        )
        stream.write("\n")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_values(values: Iterable[int]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(f"{value}\n".encode("ascii"))
    return digest.hexdigest()


def parts_sentinel(parts_dir: Path) -> Path:
    return parts_dir / PARTS_SENTINEL_NAME


def initialize_parts_dir(parts_dir: Path) -> None:
    """Create a downloader-owned cache directory and its deletion sentinel."""
    sentinel = parts_sentinel(parts_dir)
    if parts_dir.exists():
        if not parts_dir.is_dir():
            raise DownloadError(f"Parts path exists but is not a directory: {parts_dir}")
        try:
            owner = sentinel.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise DownloadError(
                f"Refusing to use an existing unowned parts directory: {parts_dir}"
            ) from exc
        if owner != LAYER_URL:
            raise DownloadError(
                f"Refusing to use a parts directory owned by another source: {parts_dir}"
            )
        return
    parts_dir.mkdir(parents=True)
    sentinel.write_text(f"{LAYER_URL}\n", encoding="utf-8")


def reset_owned_parts_dir(parts_dir: Path) -> None:
    """Delete only a cache directory explicitly created by this downloader."""
    if not parts_dir.exists():
        return
    sentinel = parts_sentinel(parts_dir)
    try:
        owner = sentinel.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DownloadError(
            f"Refusing to remove an unowned parts directory (missing sentinel): {parts_dir}"
        ) from exc
    if owner != LAYER_URL:
        raise DownloadError(
            f"Refusing to remove a parts directory owned by another source: {parts_dir}"
        )
    shutil.rmtree(parts_dir)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def layer_edit_timestamp(layer: dict[str, Any]) -> int | None:
    editing_info = layer.get("editingInfo")
    if not isinstance(editing_info, dict):
        return None
    value = editing_info.get("lastEditDate")
    return value if isinstance(value, int) else None


def fetch_source_snapshot() -> tuple[dict[str, Any], dict[str, Any], list[int]]:
    service = request_json(SERVICE_URL, {"f": "json"})
    layer = request_json(LAYER_URL, {"f": "json"})

    count_response = request_json(
        QUERY_URL,
        {"where": "1=1", "returnCountOnly": "true", "f": "json"},
    )
    count = count_response.get("count")
    if count != EXPECTED_FEATURE_COUNT:
        raise DownloadError(
            f"Expected {EXPECTED_FEATURE_COUNT:,} source features, but the server reports {count!r}. "
            "Review the source version before accepting a changed dataset."
        )

    ids_response = request_json(
        QUERY_URL,
        {"where": "1=1", "returnIdsOnly": "true", "f": "json"},
    )
    object_id_field = layer.get("objectIdField")
    if ids_response.get("objectIdFieldName") != object_id_field:
        raise DownloadError(
            "The object-ID field differs between layer metadata and the IDs response: "
            f"{object_id_field!r} vs {ids_response.get('objectIdFieldName')!r}"
        )

    raw_ids = ids_response.get("objectIds")
    if not isinstance(raw_ids, list) or not all(isinstance(value, int) for value in raw_ids):
        raise DownloadError("The source did not return an integer objectIds array")
    object_ids = sorted(raw_ids)
    if len(object_ids) != count or len(set(object_ids)) != count:
        raise DownloadError(
            f"Source ID validation failed: count={count}, ids={len(object_ids)}, "
            f"unique_ids={len(set(object_ids))}"
        )

    return service, layer, object_ids


def field_names(layer: dict[str, Any]) -> list[str]:
    fields = layer.get("fields")
    if not isinstance(fields, list):
        raise DownloadError("Layer metadata has no fields array")
    names = [field.get("name") for field in fields if isinstance(field, dict)]
    if not names or not all(isinstance(name, str) and name for name in names):
        raise DownloadError("Layer metadata contains an invalid field definition")
    return names


def iter_positions(coordinates: Any) -> Iterator[tuple[float, float]]:
    if (
        isinstance(coordinates, list)
        and len(coordinates) >= 2
        and isinstance(coordinates[0], (int, float))
        and isinstance(coordinates[1], (int, float))
    ):
        yield float(coordinates[0]), float(coordinates[1])
        return
    if isinstance(coordinates, list):
        for child in coordinates:
            yield from iter_positions(child)


def validate_feature(
    feature: Any,
    *,
    expected_fields: set[str],
    object_id_field: str,
) -> tuple[int, str, int]:
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise DownloadError("A page contains an invalid GeoJSON Feature")

    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise DownloadError("A feature has no properties object")
    actual_fields = set(properties)
    if actual_fields != expected_fields:
        raise DownloadError(
            "A feature does not contain the complete source schema; "
            f"missing={sorted(expected_fields - actual_fields)}, "
            f"unexpected={sorted(actual_fields - expected_fields)}"
        )
    object_id = properties.get(object_id_field)
    if not isinstance(object_id, int):
        raise DownloadError(f"Feature object ID is not an integer: {object_id!r}")

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise DownloadError(f"Feature {object_id} has no geometry")
    geometry_type = geometry.get("type")
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise DownloadError(f"Feature {object_id} has unexpected geometry type {geometry_type!r}")

    coordinate_count = 0
    for longitude, latitude in iter_positions(geometry.get("coordinates")):
        coordinate_count += 1
        if not (math.isfinite(longitude) and math.isfinite(latitude)):
            raise DownloadError(f"Feature {object_id} contains a non-finite coordinate")
        if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
            raise DownloadError(
                f"Feature {object_id} is not in EPSG:4326 longitude/latitude: "
                f"({longitude}, {latitude})"
            )
    if coordinate_count == 0:
        raise DownloadError(f"Feature {object_id} has empty geometry coordinates")

    return object_id, geometry_type, coordinate_count


def validate_page(
    page: Any,
    *,
    expected_ids: list[int],
    expected_fields: set[str],
    object_id_field: str,
) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    if not isinstance(page, dict) or page.get("type") != "FeatureCollection":
        raise DownloadError("ArcGIS page is not a GeoJSON FeatureCollection")
    features = page.get("features")
    if not isinstance(features, list):
        raise DownloadError("ArcGIS page has no features array")

    page_ids: list[int] = []
    geometry_types: dict[str, int] = {}
    coordinate_count = 0
    for feature in features:
        object_id, geometry_type, positions = validate_feature(
            feature,
            expected_fields=expected_fields,
            object_id_field=object_id_field,
        )
        page_ids.append(object_id)
        geometry_types[geometry_type] = geometry_types.get(geometry_type, 0) + 1
        coordinate_count += positions

    if page_ids != expected_ids:
        raise DownloadError(
            "Page object IDs differ from the source snapshot: "
            f"expected {expected_ids[:1]}..{expected_ids[-1:]}, "
            f"received {page_ids[:1]}..{page_ids[-1:]}, "
            f"expected_count={len(expected_ids)}, received_count={len(page_ids)}"
        )
    return features, geometry_types, coordinate_count


def page_path(parts_dir: Path, offset: int, expected_ids: list[int]) -> Path:
    return parts_dir / (
        f"page_{offset:09d}_{offset + len(expected_ids) - 1:09d}_"
        f"oid_{expected_ids[0]}_{expected_ids[-1]}.geojson"
    )


def download_pages(
    *,
    parts_dir: Path,
    object_ids: list[int],
    page_size: int,
    expected_fields: set[str],
    object_id_field: str,
) -> list[Path]:
    pages: list[Path] = []
    page_total = math.ceil(len(object_ids) / page_size)

    for page_number, offset in enumerate(range(0, len(object_ids), page_size), start=1):
        expected_page_ids = object_ids[offset : offset + page_size]
        path = page_path(parts_dir, offset, expected_page_ids)
        if path.exists():
            try:
                existing_page = json.loads(path.read_text(encoding="utf-8"))
                validate_page(
                    existing_page,
                    expected_ids=expected_page_ids,
                    expected_fields=expected_fields,
                    object_id_field=object_id_field,
                )
                print(
                    f"[resume] page {page_number:02d}/{page_total}: "
                    f"{len(expected_page_ids):,} features"
                )
                pages.append(path)
                continue
            except (OSError, json.JSONDecodeError, DownloadError) as exc:
                print(f"[resume] invalid cached page {path.name}: {exc}; downloading again")

        page = request_json(
            QUERY_URL,
            {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": str(OUTPUT_EPSG),
                "orderByFields": f"{object_id_field} ASC",
                "resultOffset": str(offset),
                "resultRecordCount": str(len(expected_page_ids)),
                "f": "geojson",
            },
        )
        features, _, _ = validate_page(
            page,
            expected_ids=expected_page_ids,
            expected_fields=expected_fields,
            object_id_field=object_id_field,
        )
        atomic_write_json(path, page)
        print(
            f"[download] page {page_number:02d}/{page_total}: "
            f"{len(features):,} features, OID {expected_page_ids[0]}..{expected_page_ids[-1]}"
        )
        pages.append(path)

    return pages


def combine_pages(
    *,
    pages: list[Path],
    output: Path,
    object_ids: list[int],
    expected_fields: set[str],
    object_id_field: str,
) -> tuple[dict[str, int], int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    geometry_types: dict[str, int] = {}
    coordinate_count = 0
    written_ids: list[int] = []
    first = True

    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(
            '{"type":"FeatureCollection","name":"korea_flood_2002_2022",'
            '"properties":{"source":'
        )
        stream.write(json.dumps(LAYER_URL, ensure_ascii=False, separators=(",", ":")))
        stream.write(
            f',"sourceFeatureCount":{len(object_ids)},'
            f'"outputCrs":"EPSG:{OUTPUT_EPSG}"}},"features":['
        )

        offset = 0
        for path in pages:
            page = json.loads(path.read_text(encoding="utf-8"))
            page_features = page.get("features")
            if not isinstance(page_features, list):
                raise DownloadError(f"Cached page {path.name} has no features array")
            expected_page_ids = object_ids[offset : offset + len(page_features)]
            features, page_geometry_types, page_coordinate_count = validate_page(
                page,
                expected_ids=expected_page_ids,
                expected_fields=expected_fields,
                object_id_field=object_id_field,
            )
            for feature in features:
                if not first:
                    stream.write(",")
                json.dump(feature, stream, ensure_ascii=False, separators=(",", ":"))
                first = False
                written_ids.append(feature["properties"][object_id_field])
            for geometry_type, count in page_geometry_types.items():
                geometry_types[geometry_type] = geometry_types.get(geometry_type, 0) + count
            coordinate_count += page_coordinate_count
            offset += len(features)

        stream.write("]}\n")

    if written_ids != object_ids:
        temporary.unlink(missing_ok=True)
        raise DownloadError(
            f"Combined output ID validation failed: expected={len(object_ids)}, "
            f"written={len(written_ids)}, unique={len(set(written_ids))}"
        )
    temporary.replace(output)
    return geometry_types, coordinate_count


def inspect_topology(
    *,
    pages: list[Path],
    object_id_field: str,
) -> dict[str, Any]:
    """Report source topology defects without changing the raw geometries.

    Shapely is part of the repository requirements, but the downloader remains
    usable with the Python standard library alone.  Structural geometry and CRS
    checks are always performed; this additional self-intersection check is
    recorded when Shapely is installed.
    """

    try:
        from shapely.geometry import shape
        from shapely.validation import explain_validity
    except ImportError:
        return {
            "checked": False,
            "reason": "Shapely is not installed; structural geometry and CRS checks still passed.",
        }

    feature_count = 0
    empty_object_ids: list[int] = []
    invalid: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    for path in pages:
        page = json.loads(path.read_text(encoding="utf-8"))
        for feature in page["features"]:
            feature_count += 1
            object_id = feature["properties"][object_id_field]
            geometry = shape(feature["geometry"])
            if geometry.is_empty:
                empty_object_ids.append(object_id)
            if not geometry.is_valid:
                reason = explain_validity(geometry)
                reason_name = reason.split("[", 1)[0]
                reason_counts[reason_name] += 1
                invalid.append({"objectid": object_id, "reason": reason})

    return {
        "checked": True,
        "feature_count": feature_count,
        "valid_count": feature_count - len(invalid),
        "invalid_count": len(invalid),
        "empty_count": len(empty_object_ids),
        "invalid_reason_counts": dict(reason_counts),
        "invalid_features": invalid,
        "empty_object_ids": empty_object_ids,
        "raw_geometry_modified": False,
    }


def validate_completed_output(
    *,
    output: Path,
    manifest_path: Path,
    object_ids: list[int],
) -> bool:
    if not (output.exists() and manifest_path.exists()):
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        manifest.get("feature_count") == len(object_ids)
        and manifest.get("object_ids", {}).get("sha256") == sha256_values(object_ids)
        and manifest.get("output", {}).get("sha256") == sha256_file(output)
        and manifest.get("output", {}).get("bytes") == output.stat().st_size
        and manifest.get("source", {}).get("layer_url") == LAYER_URL
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and verify the nationwide Esri Korea flood-trace GeoJSON."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--parts-dir", type=Path, default=DEFAULT_PARTS_DIR)
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Features per request; automatically capped to the source maxRecordCount.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild the final GeoJSON even when its manifest and checksum are valid.",
    )
    parser.add_argument(
        "--reset-parts",
        action="store_true",
        help="Discard this downloader's exact cached-page directory before starting.",
    )
    parser.add_argument(
        "--keep-parts",
        action="store_true",
        help="Keep validated page files after the final output is complete.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    manifest_path = args.manifest.resolve()
    parts_dir = args.parts_dir.resolve()

    service, layer, object_ids = fetch_source_snapshot()
    source_max = layer.get("maxRecordCount")
    if not isinstance(source_max, int) or source_max <= 0:
        raise DownloadError(f"Invalid source maxRecordCount: {source_max!r}")
    if args.page_size <= 0:
        raise DownloadError("--page-size must be positive")
    page_size = min(args.page_size, source_max)

    object_id_field = layer.get("objectIdField")
    if not isinstance(object_id_field, str) or not object_id_field:
        raise DownloadError("Layer metadata has no objectIdField")
    expected_field_names = field_names(layer)
    expected_fields = set(expected_field_names)

    source_spatial_reference = layer.get("spatialReference", {})
    source_wkid = (
        source_spatial_reference.get("latestWkid")
        or source_spatial_reference.get("wkid")
        if isinstance(source_spatial_reference, dict)
        else None
    )
    if source_wkid != 3857:
        raise DownloadError(f"Expected source EPSG:3857, received {source_wkid!r}")
    if layer.get("geometryType") != "esriGeometryPolygon":
        raise DownloadError(f"Unexpected source geometry type: {layer.get('geometryType')!r}")
    supported_formats = str(layer.get("supportedQueryFormats", ""))
    if "geoJSON" not in supported_formats:
        raise DownloadError(f"The layer does not advertise GeoJSON queries: {supported_formats!r}")

    print(
        f"[source] {len(object_ids):,} features, source EPSG:{source_wkid}, "
        f"output EPSG:{OUTPUT_EPSG}, page size {page_size:,}"
    )
    if not args.force and validate_completed_output(
        output=output,
        manifest_path=manifest_path,
        object_ids=object_ids,
    ):
        print(f"[done] existing verified download: {display_path(output)}")
        return

    if args.reset_parts:
        reset_owned_parts_dir(parts_dir)
    initialize_parts_dir(parts_dir)

    state = {
        "source_layer_url": LAYER_URL,
        "source_feature_count": len(object_ids),
        "source_object_ids_sha256": sha256_values(object_ids),
        "source_last_edit_epoch_ms": layer_edit_timestamp(layer),
        "page_size": page_size,
        "output_epsg": OUTPUT_EPSG,
    }
    state_path = parts_dir / "state.json"
    if state_path.exists():
        try:
            previous_state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DownloadError(
                f"Cached state is corrupt. Re-run with --reset-parts: {state_path}"
            ) from exc
        if previous_state != state:
            raise DownloadError(
                f"Cached pages belong to another source snapshot. Re-run with --reset-parts: {state_path}"
            )
    else:
        atomic_write_json(state_path, state, pretty=True)

    pages = download_pages(
        parts_dir=parts_dir,
        object_ids=object_ids,
        page_size=page_size,
        expected_fields=expected_fields,
        object_id_field=object_id_field,
    )

    # Make sure the service did not change while the paged download ran.
    _, final_layer, final_object_ids = fetch_source_snapshot()
    if (
        final_object_ids != object_ids
        or layer_edit_timestamp(final_layer) != layer_edit_timestamp(layer)
    ):
        raise DownloadError(
            "The source changed during download. Cached pages were kept; restart with --reset-parts."
        )

    geometry_types, coordinate_count = combine_pages(
        pages=pages,
        output=output,
        object_ids=object_ids,
        expected_fields=expected_fields,
        object_id_field=object_id_field,
    )
    topology = inspect_topology(pages=pages, object_id_field=object_id_field)
    if topology.get("checked") and topology.get("invalid_count"):
        print(
            f"[warn] retained {topology['invalid_count']:,} source geometries with invalid "
            "topology; see the manifest before spatial operations",
            file=sys.stderr,
        )

    downloaded_at = datetime.now(timezone.utc)
    manifest = {
        "dataset": "전국 침수흔적도(2002-2022)",
        "downloaded_at_utc": downloaded_at.isoformat(),
        "feature_count": len(object_ids),
        "attribute_field_count": len(expected_field_names),
        "attribute_fields": expected_field_names,
        "geometry": {
            "source_esri_type": layer.get("geometryType"),
            "output_types": geometry_types,
            "coordinate_position_count": coordinate_count,
            "missing_geometry_count": 0,
            "topology": topology,
        },
        "object_ids": {
            "field": object_id_field,
            "minimum": object_ids[0],
            "maximum": object_ids[-1],
            "unique_count": len(object_ids),
            "sha256": sha256_values(object_ids),
        },
        "output": {
            "path": display_path(output),
            "format": "GeoJSON FeatureCollection (RFC 7946 longitude/latitude)",
            "crs": f"EPSG:{OUTPUT_EPSG} / OGC:CRS84 coordinate order",
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
        },
        "paging": {
            "source_max_record_count": source_max,
            "requested_page_size": page_size,
            "page_count": len(pages),
        },
        "source": {
            "service_url": SERVICE_URL,
            "layer_url": LAYER_URL,
            "item_url": ITEM_URL,
            "original_approval_url": ORIGINAL_APPROVAL_URL,
            "service_current_version": service.get("currentVersion"),
            "layer_name": layer.get("name"),
            "source_crs": f"EPSG:{source_wkid}",
            "source_last_edit_epoch_ms": layer_edit_timestamp(layer),
            "supported_query_formats": layer.get("supportedQueryFormats"),
            "copyright_text": layer.get("copyrightText"),
            "item_rights_notice": "All rights reserved by Ministry of the Interior and Safety of Korea.",
            "redistribution_review": "Raw nationwide GeoJSON is kept out of Git until reuse and redistribution terms are confirmed.",
        },
        "validation": {
            "expected_feature_count": EXPECTED_FEATURE_COUNT,
            "feature_count_matches": len(object_ids) == EXPECTED_FEATURE_COUNT,
            "all_object_ids_unique_and_match_source_snapshot": True,
            "all_source_attribute_fields_present": True,
            "all_geometries_present": True,
            "all_coordinates_valid_longitude_latitude": True,
            "source_snapshot_unchanged_during_download": True,
        },
    }
    atomic_write_json(manifest_path, manifest, pretty=True)

    if not args.keep_parts:
        reset_owned_parts_dir(parts_dir)

    print(
        f"[done] {len(object_ids):,} features -> {display_path(output)} "
        f"({output.stat().st_size / (1024 * 1024):.1f} MiB)"
    )
    print(f"[done] manifest -> {display_path(manifest_path)}")


if __name__ == "__main__":
    try:
        main()
    except (DownloadError, OSError) as exc:
        raise SystemExit(f"error: {exc}") from exc
