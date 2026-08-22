#!/usr/bin/env python3
"""Check the dependency-free projection against pyproj.

``serverless/projection.py`` replaces pyproj in the Lambda so the package
carries no compiled extensions and no PROJ data directory. That trade is only
safe if the arithmetic actually matches, so this compares the two across the
country and fails loudly if they drift.

Run it whenever projection.py changes. It needs pyproj, which the local
environment has and the Lambda deliberately does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "serverless"))

from projection import grid_to_wgs84, wgs84_to_grid  # noqa: E402

# A 100 m grid cell tolerates far more than this; the bar is set at the
# millimetre level so any real regression is obvious rather than debatable.
MAX_FORWARD_MM = 10.0
MAX_ROUNDTRIP_MM = 50.0

# Korea including Jeju and the eastern islands.
LON_RANGE = (124.5, 131.5)
LAT_RANGE = (33.0, 38.7)


def main() -> None:
    from pyproj import Transformer

    forward = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    rng = np.random.default_rng(0)
    lons = rng.uniform(*LON_RANGE, 20_000)
    lats = rng.uniform(*LAT_RANGE, 20_000)

    expected_x, expected_y = forward.transform(lons, lats)
    mine = np.array([wgs84_to_grid(lon, lat) for lon, lat in zip(lons, lats)])
    offset_mm = np.hypot(mine[:, 0] - expected_x, mine[:, 1] - expected_y) * 1000.0

    roundtrip = np.array(
        [grid_to_wgs84(*wgs84_to_grid(lon, lat)) for lon, lat in zip(lons[:5000], lats[:5000])]
    )
    # Degrees to metres, using coarse per-degree scales; precise enough to
    # catch a broken inverse without another projection call.
    roundtrip_mm = (
        np.hypot(
            (roundtrip[:, 0] - lons[:5000]) * 88_000.0,
            (roundtrip[:, 1] - lats[:5000]) * 111_000.0,
        )
        * 1000.0
    )

    print(f"표본 {len(lons):,}점 (경도 {LON_RANGE}, 위도 {LAT_RANGE})")
    print(f"  정방향 최대 오차 {offset_mm.max():.3f} mm (중앙값 {np.median(offset_mm):.4f} mm)")
    print(f"  왕복  최대 오차 {roundtrip_mm.max():.3f} mm")
    print(f"  격자 셀 100 m 대비 {offset_mm.max() / 1000.0 / 100.0 * 100:.7f} %")

    failures = []
    if offset_mm.max() > MAX_FORWARD_MM:
        failures.append(f"정방향 {offset_mm.max():.3f} mm > 허용 {MAX_FORWARD_MM} mm")
    if roundtrip_mm.max() > MAX_ROUNDTRIP_MM:
        failures.append(f"왕복 {roundtrip_mm.max():.3f} mm > 허용 {MAX_ROUNDTRIP_MM} mm")

    if failures:
        for message in failures:
            print(f"[FAIL] {message}", file=sys.stderr)
        raise SystemExit(1)
    print("[OK] pyproj와 일치한다")


if __name__ == "__main__":
    main()
