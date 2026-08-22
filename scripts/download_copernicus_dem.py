#!/usr/bin/env python3
"""Download Copernicus GLO-30 DSM tiles covering South Korea.

Terrain is the strongest signal Waterpark has found.  Measured on Gyeongbuk,
a building sitting 0-2m above its surroundings flooded 35.5% of the time
while one 20m above never did, and that single rule outperformed the nine
feature XGBoost model (PR-AUC 0.249 against 0.099).  The nationwide overlap
tables carry no elevation at all, so the strongest feature is missing exactly
where the training data now lives.

The DSM tiles that produced the Gyeongbuk figures are no longer on disk, so
this re-acquires them for the whole country from the AWS Open Data mirror,
which needs no credentials.

Tiles are 1x1 degree COGs named by their south-west corner:

    Copernicus_DSM_COG_10_N37_00_E126_00_DEM/...DEM.tif

Ocean-only tiles do not exist in the archive; a 404 is recorded as absent
rather than treated as a failure.  Downloads are resumable: a tile that is
already present and opens cleanly is skipped.

Note the model type.  GLO-30 is a DSM, not a DTM -- it includes buildings and
tree canopy, so a sampled value is surface height rather than ground height.
That limitation is inherited from the Gyeongbuk work and is recorded in the
manifest rather than silently corrected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from data_paths import ROOT

DEM_DIR = ROOT / "data/raw/dem"
MANIFEST = DEM_DIR / "copernicus_glo30_korea.manifest.json"

BUCKET_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
USER_AGENT = "Waterpark-data-collector/1.0"

# South Korea including Jeju (33N) and the eastern islands (E131).
DEFAULT_LAT_RANGE = (33, 38)
DEFAULT_LON_RANGE = (124, 131)


class DemError(RuntimeError):
    pass


def tile_stem(lat: int, lon: int) -> str:
    return f"Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM"


def tile_url(lat: int, lon: int) -> str:
    stem = tile_stem(lat, lon)
    return f"{BUCKET_BASE}/{stem}/{stem}.tif"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_tile(path: Path, lat: int, lon: int) -> dict[str, Any]:
    """Open the tile and check it really covers the square it is named for."""
    import rasterio

    with rasterio.open(path) as src:
        bounds = src.bounds
        crs = str(src.crs)
        info = {
            "width": src.width,
            "height": src.height,
            "crs": crs,
            "dtype": str(src.dtypes[0]),
            "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
            "nodata": src.nodata,
        }
    if "4326" not in crs:
        raise DemError(f"{path.name} is not EPSG:4326 (got {crs})")
    # Allow the half-pixel edge offset COGs carry.
    tolerance = 0.01
    if not (
        bounds.left <= lon + tolerance
        and bounds.right >= lon + 1 - tolerance
        and bounds.bottom <= lat + tolerance
        and bounds.top >= lat + 1 - tolerance
    ):
        raise DemError(f"{path.name} bounds {info['bounds']} do not cover N{lat} E{lon}")
    return info


def download_tile(lat: int, lon: int, retries: int = 4) -> tuple[str, dict[str, Any]]:
    """Fetch one tile. Returns (status, info) where status is ok/absent."""
    path = DEM_DIR / f"{tile_stem(lat, lon)}.tif"
    if path.exists() and path.stat().st_size > 0:
        try:
            info = verify_tile(path, lat, lon)
            info["bytes"] = path.stat().st_size
            return "cached", info
        except Exception:
            # A truncated leftover is worth replacing, not keeping.
            path.unlink(missing_ok=True)

    url = tile_url(lat, lon)
    temporary = path.with_suffix(".tif.part")
    delay = 2.0
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=180) as response, temporary.open("wb") as out:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            temporary.replace(path)
            info = verify_tile(path, lat, lon)
            info["bytes"] = path.stat().st_size
            info["sha256"] = sha256_of(path)
            return "downloaded", info
        except HTTPError as exc:
            temporary.unlink(missing_ok=True)
            if exc.code == 404:
                # Ocean-only squares are simply not published.
                return "absent", {"http_status": 404}
            if attempt == retries - 1:
                raise DemError(f"N{lat} E{lon}: HTTP {exc.code} {exc.reason}") from None
        except (URLError, TimeoutError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            if attempt == retries - 1:
                raise DemError(f"N{lat} E{lon}: {type(exc).__name__}") from None
        except DemError:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise
        time.sleep(delay)
        delay = min(delay * 2, 20.0)
    raise DemError(f"N{lat} E{lon}: exhausted retries")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat-min", type=int, default=DEFAULT_LAT_RANGE[0])
    parser.add_argument("--lat-max", type=int, default=DEFAULT_LAT_RANGE[1])
    parser.add_argument("--lon-min", type=int, default=DEFAULT_LON_RANGE[0])
    parser.add_argument("--lon-max", type=int, default=DEFAULT_LON_RANGE[1])
    args = parser.parse_args()

    DEM_DIR.mkdir(parents=True, exist_ok=True)
    squares = [
        (lat, lon)
        for lat in range(args.lat_min, args.lat_max + 1)
        for lon in range(args.lon_min, args.lon_max + 1)
    ]
    print(
        f"[plan] N{args.lat_min}~N{args.lat_max} / E{args.lon_min}~E{args.lon_max}"
        f" = {len(squares)}개 1도 타일 확인",
        flush=True,
    )

    tiles: dict[str, Any] = {}
    counts = {"downloaded": 0, "cached": 0, "absent": 0}
    total_bytes = 0
    started = time.time()

    for index, (lat, lon) in enumerate(squares, start=1):
        name = f"N{lat}E{lon}"
        try:
            status, info = download_tile(lat, lon)
        except DemError as exc:
            print(f"  [fail] {name}: {exc}", file=sys.stderr, flush=True)
            tiles[name] = {"status": "failed", "error": str(exc)}
            continue
        counts[status] += 1
        info["status"] = status
        tiles[name] = info
        if status != "absent":
            total_bytes += info.get("bytes", 0)
            print(
                f"  [{index}/{len(squares)}] {name} {status}"
                f" {info.get('bytes', 0) / 1e6:.1f}MB",
                flush=True,
            )

    manifest = {
        "dataset": "Copernicus DEM GLO-30 (DSM)",
        "source": "AWS Open Data — s3://copernicus-dem-30m (no credentials required)",
        "source_url": BUCKET_BASE,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "square_range": {
            "lat": [args.lat_min, args.lat_max],
            "lon": [args.lon_min, args.lon_max],
        },
        "counts": counts,
        "total_bytes": total_bytes,
        "tiles": tiles,
        "model_type": "DSM — includes buildings and vegetation, not bare ground",
        "notes": [
            "타일이 없는 1도 격자는 해당 영역이 전부 바다라 아카이브에 없는 것이며 수집 실패가 아니다.",
            "각 타일은 열어서 CRS와 경계가 이름과 일치하는지 확인한 뒤 기록했다.",
        ],
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"[done] 신규 {counts['downloaded']} / 기존 {counts['cached']}"
        f" / 없음(해상) {counts['absent']}"
        f" | {total_bytes / 1e6:.0f}MB | {(time.time() - started) / 60:.1f}분"
    )
    print(f"[done] manifest -> {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except DemError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
