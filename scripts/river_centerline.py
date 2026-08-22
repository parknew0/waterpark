#!/usr/bin/env python3
"""Read the national river centreline shapefile by river grade.

The 국토지리정보원 국가기본도 하천중심선 holds 3,224,769 polylines, and 84.5%
of them are 세류 -- gullies and rivulets.  Distance to one of those says
little about flood risk, so callers pick which grades to load rather than
treating every line as "a river".

Grades come from ``RIVER_SE``, which is populated on every record.  The name
and number columns are not: ``RIVER_NM`` is filled on 6.5% of rows and
``RIVER_NO`` on 5.4%, which VWorld confirmed is expected for this
photogrammetry-derived layer.  Names are only useful for display, so nothing
here depends on them.

Coordinates stay in the file's native EPSG:5179 (UTM-K), a metric projection
covering the whole country, so distances come out in metres without
reprojecting a 1 GB geometry file.  Callers project their points instead.
"""

from __future__ import annotations

import mmap
import struct
from pathlib import Path
from typing import Iterator

from data_paths import ROOT

RIVER_DIR = ROOT / "data/raw/river-centerline"
RIVER_STEM = "TN_RIVER_CTLN"

SHAPE_TYPE_NULL = 0
SHAPE_TYPE_POLYLINE = 3

GRADE_NAMES = {
    "RVC001": "국가하천",
    "RVC002": "지방하천",
    "RVC003": "소하천",
    "RVC004": "기타하천",
    "RVC005": "세류",
}
# Grades worth measuring distance to by default.  세류 is excluded because it
# dominates the file by count while carrying the least flood signal, and
# 기타하천 is excluded because the definition is unclear.
MAIN_GRADES = ("RVC001", "RVC002", "RVC003")

SOURCE_EPSG = 5179


class RiverError(RuntimeError):
    pass


def shp_path() -> Path:
    return RIVER_DIR / f"{RIVER_STEM}.shp"


def dbf_path() -> Path:
    return RIVER_DIR / f"{RIVER_STEM}.dbf"


def read_grades() -> list[str]:
    """RIVER_SE for every record, positionally aligned with the SHP."""
    path = dbf_path()
    if not path.exists():
        raise RiverError(f"Missing {path}")
    with path.open("rb") as stream:
        header = stream.read(32)
        row_count = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]
        fields: dict[str, tuple[int, int]] = {}
        offset = 1
        while True:
            descriptor = stream.read(32)
            if not descriptor or descriptor[0] == 0x0D:
                break
            name = descriptor[:11].split(b"\0", 1)[0].decode("ascii")
            fields[name] = (offset, descriptor[16])
            offset += descriptor[16]
        if "RIVER_SE" not in fields:
            raise RiverError("RIVER_SE column missing from the river DBF")

        field_offset, field_length = fields["RIVER_SE"]
        stream.seek(0)
        mm = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            grades: list[str] = []
            for index in range(row_count):
                start = header_length + index * record_length
                if mm[start : start + 1] == b"*":
                    grades.append("")
                    continue
                raw = mm[start + field_offset : start + field_offset + field_length]
                grades.append(raw.decode("ascii", "ignore").strip())
        finally:
            mm.close()
    return grades


def iter_polylines(wanted_grades: set[str]) -> Iterator[tuple[str, list[list[tuple[float, float]]]]]:
    """Yield (grade, parts) for every polyline whose grade is wanted.

    Records are read in file order, which matches the DBF positionally.  The
    SHP is streamed rather than loaded so the 1 GB file never sits in memory
    at once; only the selected geometry does.
    """
    grades = read_grades()
    path = shp_path()
    if not path.exists():
        raise RiverError(f"Missing {path}")

    with path.open("rb") as stream:
        mm = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            size = len(mm)
            offset = 100  # main file header
            index = 0
            while offset + 8 <= size:
                content_length_words = struct.unpack(">I", mm[offset + 4 : offset + 8])[0]
                content_start = offset + 8
                content_end = content_start + content_length_words * 2
                if content_end > size:
                    break

                grade = grades[index] if index < len(grades) else ""
                if grade in wanted_grades:
                    shape_type = struct.unpack(
                        "<I", mm[content_start : content_start + 4]
                    )[0]
                    if shape_type == SHAPE_TYPE_POLYLINE:
                        num_parts = struct.unpack(
                            "<I", mm[content_start + 36 : content_start + 40]
                        )[0]
                        num_points = struct.unpack(
                            "<I", mm[content_start + 40 : content_start + 44]
                        )[0]
                        parts_start = content_start + 44
                        points_start = parts_start + num_parts * 4
                        part_offsets = list(
                            struct.unpack(
                                f"<{num_parts}I",
                                mm[parts_start : parts_start + num_parts * 4],
                            )
                        )
                        part_offsets.append(num_points)

                        parts: list[list[tuple[float, float]]] = []
                        for part in range(num_parts):
                            begin, end = part_offsets[part], part_offsets[part + 1]
                            if end - begin < 2:
                                continue
                            chunk = mm[
                                points_start + begin * 16 : points_start + end * 16
                            ]
                            coords = struct.unpack(f"<{(end - begin) * 2}d", chunk)
                            parts.append(list(zip(coords[0::2], coords[1::2])))
                        if parts:
                            yield grade, parts
                    elif shape_type != SHAPE_TYPE_NULL:
                        raise RiverError(
                            f"Record {index} has unsupported shape type {shape_type}"
                        )

                offset = content_end
                index += 1
        finally:
            mm.close()


def load_by_grade(grades: tuple[str, ...] = MAIN_GRADES) -> dict[str, list]:
    """Build shapely LineStrings grouped by grade, in EPSG:5179 metres."""
    from shapely.geometry import LineString

    wanted = set(grades)
    out: dict[str, list] = {grade: [] for grade in grades}
    for grade, parts in iter_polylines(wanted):
        for coords in parts:
            out[grade].append(LineString(coords))
    return out
