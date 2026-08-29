#!/usr/bin/env python3
"""A nationwide 법정동코드 -> centroid table, built from the building extract.

Several public flood datasets carry an address and no coordinate. Where the
parcel itself can be found this project joins on PNU, which is exact. But a
좋은 fraction of records point at a river, an embankment, or farmland -- places
with no building on the parcel -- and those fall through.

A 법정동 centroid is the honest fallback: coarser than a parcel, but bounded
and reportable. It is derived here rather than downloaded so it always matches
the same building extract the PNU join uses, and so the pipeline keeps working
without another external dependency.

Only each shape's bounding box is read; the polygon rings are skipped.
"""

from __future__ import annotations

import glob
import json
import os
import struct
from collections import defaultdict
from pathlib import Path

import pyproj

NATIONAL = "data/raw/vworld-buildings/national"
OUT = Path("data/interim/geocoding/legal_dong_centroids.json")
PNU_OFFSET, PNU_LEN = 38, 19
TO_WGS84 = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform


def dbf_pnus(path: str) -> list[str]:
    out: list[str] = []
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
                out.append(buffer[start : start + PNU_LEN].decode("ascii", "replace"))
            buffer = buffer[whole * record_len :]
    return out[:count]


def shape_centres(shp: str) -> list[tuple[float, float] | None]:
    """Every record's bbox centre, in order, read sequentially."""
    out: list[tuple[float, float] | None] = []
    with open(shp, "rb") as handle:
        handle.seek(100)
        while True:
            head = handle.read(8)
            if len(head) < 8:
                break
            length = struct.unpack(">I", head[4:8])[0] * 2
            body = handle.read(length)
            if len(body) < 4:
                break
            kind = struct.unpack("<I", body[:4])[0]
            if kind == 1 and len(body) >= 20:
                x, y = struct.unpack("<2d", body[4:20])
                out.append((x, y))
            elif kind in (3, 5, 15, 23, 25) and len(body) >= 36:
                x0, y0, x1, y1 = struct.unpack("<4d", body[4:36])
                out.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0))
            else:
                out.append(None)
    return out


def main() -> None:
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    for dbf in sorted(glob.glob(f"{NATIONAL}/*/*.dbf")):
        shp = dbf[:-4] + ".shp"
        if not os.path.exists(shp):
            continue
        pnus = dbf_pnus(dbf)
        centres = shape_centres(shp)
        n = min(len(pnus), len(centres))
        for i in range(n):
            centre = centres[i]
            if centre is None:
                continue
            entry = sums[pnus[i][:10]]
            entry[0] += centre[0]
            entry[1] += centre[1]
            entry[2] += 1
        print(f"  {os.path.basename(dbf)[:-4]:<30} {n:>9,}건  법정동 누적 {len(sums):,}")

    table = {}
    for code, (sx, sy, count) in sums.items():
        if count == 0 or not code.isdigit():
            continue
        lon, lat = TO_WGS84(sx / count, sy / count)
        table[code] = [round(lon, 6), round(lat, 6), count]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(table), encoding="utf-8")
    print(f"\n[결과] 법정동 {len(table):,}개 -> {OUT}  ({OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
