#!/usr/bin/env python3
"""Locate 행정동-coded addresses by matching the 지번 within its 시군구.

The 피해침수 records carry 행정동코드, and PNU is built from 법정동코드 -- two
code systems that share only their leading five digits. Rather than obtain a
행정동↔법정동 table, this recovers the 법정동 from the parcel number itself: a
본번-부번 pair is close to unique inside one 시군구, so scanning the building
extract for that (시군구, 본번, 부번) usually yields exactly one 법정동, and
with it a coordinate.

Where several 법정동 in the same 시군구 share a parcel number the answer is
ambiguous; those are reported and dropped rather than guessed, because a
wrong 법정동 places the point in a different neighbourhood entirely.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import struct
from collections import defaultdict
from pathlib import Path

import pyproj

NATIONAL = "data/raw/vworld-buildings/national"
PNU_OFFSET, PNU_LEN = 38, 19
TO_WGS84 = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform


def dbf_pnus(path: str) -> list[bytes]:
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
    with open(shx, "rb") as handle:
        handle.seek(100)
        index = handle.read()
    out: dict[int, tuple[float, float]] = {}
    with open(shp, "rb") as handle:
        for i in sorted(wanted):
            if (i + 1) * 8 > len(index):
                continue
            offset = struct.unpack(">I", index[i * 8 : i * 8 + 4])[0] * 2
            handle.seek(offset + 8)
            kind = struct.unpack("<I", handle.read(4))[0]
            if kind == 1:
                x, y = struct.unpack("<2d", handle.read(16))
            elif kind in (3, 5, 15, 23, 25):
                x0, y0, x1, y1 = struct.unpack("<4d", handle.read(32))
                x, y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            else:
                continue
            out[i] = (x, y)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True, help='["시군구본번부번", ...]')
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    wanted = set(json.loads(args.targets.read_text(encoding="utf-8")))
    print(f"[대상] (시군구+본번+부번) 조합 {len(wanted):,}개")

    # key -> {법정동코드: 첫 레코드 위치}
    found: dict[str, dict[str, tuple[str, int]]] = defaultdict(dict)
    for dbf in sorted(glob.glob(f"{NATIONAL}/*/*.dbf")):
        shp, shx = dbf[:-4] + ".shp", dbf[:-4] + ".shx"
        if not (os.path.exists(shp) and os.path.exists(shx)):
            continue
        hits: dict[int, tuple[str, str]] = {}
        for i, raw in enumerate(dbf_pnus(dbf)):
            pnu = raw.decode("ascii", "replace")
            key = pnu[0:5] + pnu[11:19]
            if key in wanted and pnu[0:10] not in found[key]:
                hits[i] = (key, pnu[0:10])
        name = os.path.basename(dbf)[:-4]
        if not hits:
            print(f"  {name:<30} 일치 0")
            continue
        for i, (key, dong) in hits.items():
            found[key][dong] = (dbf, i)
        print(f"  {name:<30} 일치 {len(hits):>6,}  누적 키 {len(found):,}")

    # Every candidate is written out, ambiguous ones included, so a second
    # pass can break ties with knowledge this pass does not have -- which
    # 법정동 the record's 행정동 actually contains, learned from the keys that
    # resolved on their own.
    out: dict[str, dict[str, list[float]]] = {}
    by_file: dict[str, dict[int, tuple[str, str]]] = defaultdict(dict)
    for key, cands in found.items():
        for dong, (dbf, i) in cands.items():
            by_file[dbf][i] = (key, dong)
    for dbf, idx in by_file.items():
        shp, shx = dbf[:-4] + ".shp", dbf[:-4] + ".shx"
        for i, (x, y) in shape_centres(shp, shx, set(idx)).items():
            key, dong = idx[i]
            lon, lat = TO_WGS84(x, y)
            out.setdefault(key, {})[dong] = [round(lon, 6), round(lat, 6)]

    single = sum(1 for v in out.values() if len(v) == 1)
    print(f"\n[해석] 후보 있음 {len(out):,}  단일 법정동 {single:,}  모호 {len(out)-single:,}")
    args.out.write_text(json.dumps(out), encoding="utf-8")
    print(f"[결과] {args.out}")


if __name__ == "__main__":
    main()
