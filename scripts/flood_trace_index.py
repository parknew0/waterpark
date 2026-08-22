#!/usr/bin/env python3
"""Flood-trace polygons projected to the grid's CRS, indexed for distance.

Both the grid builder and anything that needs "how far is the nearest
surveyed flood area" want the same thing: the national polygons in
EPSG:5179 metres with a spatial index over them.  Building that twice in
two places invites the two copies drifting apart, so it lives here.

Distance to a surveyed polygon carries two meanings at once, and the
service depends on both.  It is evidence -- "과거 침수 구역까지 340 m" --
and it is the surveyed test: past the buffer, a location was never looked
at, and the honest answer is UNKNOWN rather than a low risk number.
"""

from __future__ import annotations

import functools
import json
from typing import Any

from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from data_paths import ROOT

FLOOD_GEOJSON = ROOT / "data/raw/flood-trace/korea_flood_2002_2022.geojson"
GRID_EPSG = 5179


def _polygonal(geometry):
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if hasattr(geometry, "geoms"):
        parts = [g for g in geometry.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if parts:
            return unary_union(parts)
    return None


@functools.lru_cache(maxsize=1)
def _projected_geoms() -> tuple:
    if not FLOOD_GEOJSON.exists():
        raise RuntimeError(f"침수흔적 원본이 없다: {FLOOD_GEOJSON}")
    payload = json.loads(FLOOD_GEOJSON.read_text(encoding="utf-8"))
    to_grid = Transformer.from_crs("EPSG:4326", f"EPSG:{GRID_EPSG}", always_xy=True)

    geoms = []
    for feature in payload.get("features", []):
        try:
            geometry = shape(feature["geometry"])
        except Exception:
            continue
        if not geometry.is_valid:
            geometry = _polygonal(make_valid(geometry))
            if geometry is None:
                continue
        if geometry.is_empty:
            continue
        geoms.append(transform(lambda x, y: to_grid.transform(x, y), geometry))
    if not geoms:
        raise RuntimeError("투영된 침수 Polygon이 없다")
    return tuple(geoms)


def load_flood_index() -> tuple[STRtree, tuple]:
    """STRtree over the projected polygons, plus the polygons themselves.

    ``STRtree.nearest`` returns a position, so callers need the same tuple
    the tree was built from to measure the distance.
    """
    geoms = _projected_geoms()
    return STRtree(geoms), geoms


def surveyed_bounds(buffer_m: float) -> tuple[float, float, float, float]:
    """Bounding box of every surveyed polygon, expanded by the buffer."""
    geoms = _projected_geoms()
    minx = min(g.bounds[0] for g in geoms) - buffer_m
    miny = min(g.bounds[1] for g in geoms) - buffer_m
    maxx = max(g.bounds[2] for g in geoms) + buffer_m
    maxy = max(g.bounds[3] for g in geoms) + buffer_m
    return minx, miny, maxx, maxy
