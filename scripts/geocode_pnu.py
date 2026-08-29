#!/usr/bin/env python3
"""Resolve 법정동코드 + 지번 to a coordinate, using the building shapefiles.

The safetydata flood datasets carry addresses, not coordinates. An external
geocoder would work, but the answer is already on this disk: the nationwide
VWorld building extract is keyed by PNU, which is exactly 법정동코드 + 산여부 +
본번 + 부번. Joining on it is both exact and free, where a geocoder would be
approximate, rate-limited, and would send Korean addresses to a third party.

Only the PNU field and each shape's bounding box are read. DBF records are
fixed width, so the PNU is a constant slice, and a polygon's bbox sits in a
known spot at the head of its record -- the full geometry is never parsed.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import struct
import sys
from pathlib import Path

import pyproj

# The building extract is EPSG:5186 (Korea Central Belt 2010), not the 5179 the
# risk grid uses. Reading its PRJ rather than assuming: the two differ by a
# false easting large enough to land a building in the wrong province.
TO_WGS84 = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform

NATIONAL = "data/raw/vworld-buildings/national"
# Field A2 in the VWorld building DBF. Verified against the header rather than
# assumed: offset 38, width 19, which is the PNU layout.
PNU_OFFSET, PNU_LEN = 38, 19


def dbf_pnus(path: str) -> list[bytes]:
    """Every record's PNU, in record order, without parsing other fields."""
    out: list[bytes] = []
    with open(path, "rb") as handle:
        count, header_len, record_len = struct.unpack("<I H H", handle.read(32)[4:12])
        handle.seek(header_len)
        buffer = b""
        while True:
            block = handle.read(record_len * 20000)
            if not block:
                break
            buffer += block
            whole = len(buffer) // record_len
            for i in range(whole):
                start = i * record_len + PNU_OFFSET
                out.append(buffer[start : start + PNU_LEN])
            buffer = buffer[whole * record_len :]
    return out[:count]


def shape_centres(shp: str, shx: str, wanted: set[int]) -> dict[int, tuple[float, float]]:
    """Bounding-box centre for the requested record indexes only."""
    with open(shx, "rb") as handle:
        handle.seek(100)
        index = handle.read()
    centres: dict[int, tuple[float, float]] = {}
    with open(shp, "rb") as handle:
        for i in sorted(wanted):
            if (i + 1) * 8 > len(index):
                continue
            offset = struct.unpack(">I", index[i * 8 : i * 8 + 4])[0] * 2
            handle.seek(offset + 8)
            kind = struct.unpack("<I", handle.read(4))[0]
            if kind == 1:  # point
                x, y = struct.unpack("<2d", handle.read(16))
            elif kind in (3, 5, 15, 23, 25):  # polyline / polygon variants
                x0, y0, x1, y1 = struct.unpack("<4d", handle.read(32))
                x, y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            else:
                continue
            centres[i] = (x, y)
    return centres


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True, help="PNU 목록 JSON")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    wanted = set(json.loads(args.targets.read_text(encoding="utf-8")))
    print(f"[대상] PNU {len(wanted):,}개")

    resolved: dict[str, list[float]] = {}
    # A province larger than the exporter's file cap arrives split across
    # several shapefiles ("...(2).dbf" and so on). Reading only the first left
    # Gyeongbuk at 8,058 of its 3.5 GB of records.
    for dbf in sorted(glob.glob(f"{NATIONAL}/*/*.dbf")):
        shp, shx = dbf[:-4] + ".shp", dbf[:-4] + ".shx"
        if not (os.path.exists(shp) and os.path.exists(shx)):
            continue
        pnus = dbf_pnus(dbf)
        hits = {i: p.decode("ascii", "replace").strip() for i, p in enumerate(pnus)}
        hits = {i: p for i, p in hits.items() if p in wanted and p not in resolved}
        name = os.path.basename(dbf)[:-4]
        if not hits:
            print(f"  {name:<30} {len(pnus):>9,}건  일치 0")
            continue
        for i, (x, y) in shape_centres(shp, shx, set(hits)).items():
            lon, lat = TO_WGS84(x, y)
            resolved.setdefault(hits[i], [round(lon, 6), round(lat, 6)])
        print(f"  {name:<30} {len(pnus):>9,}건  일치 {len(hits):>6,}  누적 {len(resolved):,}")

    args.out.write_text(json.dumps(resolved), encoding="utf-8")
    print(f"\n[결과] {len(resolved):,}/{len(wanted):,} 해결 ({len(resolved)/len(wanted)*100:.0f}%) -> {args.out}")


if __name__ == "__main__":
    main()
