#!/usr/bin/env python3
"""Build the small stdlib-only routing bundle used by the Hinnamnor demo API.

The source road graph is reproducible OSM data.  Heavy GIS libraries are used
only here, offline.  Runtime routing reads the generated JSON and runs Dijkstra
without osmnx, geopandas, shapely, or networkx.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import osmnx as ox
from shapely.geometry import LineString, Point, mapping

from data_paths import RAW_OSM_ROUTING, ROOT

DEFAULT_GRAPH = RAW_OSM_ROUTING / "pohang-indeok-hinnamnor-drive.graphml"
DEFAULT_OUTPUT = ROOT / "serverless" / "routing" / "hinnamnor.json"
DEFAULT_SCENARIO = ROOT / "data" / "demo" / "hinnamnor-current-flood-scenario.geojson"

# A 35 m impact area over the direct crossing used by the demo.  This is a
# synthetic replay input, not a surveyed 2022 Hinnamnor flood boundary.
FLOOD_CENTER = (129.4044, 35.98517)
FLOOD_RADIUS_M = 35.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graphml", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scenario-output", type=Path, default=DEFAULT_SCENARIO)
    return parser.parse_args()


def oriented_coordinates(graph: Any, u: int, v: int, data: dict[str, Any]) -> list[list[float]]:
    geometry = data.get("geometry") or LineString(
        [(graph.nodes[u]["x"], graph.nodes[u]["y"]), (graph.nodes[v]["x"], graph.nodes[v]["y"])]
    )
    coordinates = list(geometry.coords)
    source = Point(float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"]))
    if Point(coordinates[-1]).distance(source) < Point(coordinates[0]).distance(source):
        coordinates.reverse()
    return [[round(float(lon), 7), round(float(lat), 7)] for lon, lat in coordinates]


def main() -> None:
    args = parse_args()
    graph = ox.load_graphml(args.graphml)
    _, edges = ox.graph_to_gdfs(graph)
    metric_crs = edges.estimate_utm_crs()
    edges_metric = edges.to_crs(metric_crs)
    flood_center = gpd.GeoSeries([Point(*FLOOD_CENTER)], crs="EPSG:4326").to_crs(metric_crs).iloc[0]
    current_flood = flood_center.buffer(FLOOD_RADIUS_M)
    current_flood_wgs84 = gpd.GeoSeries([current_flood], crs=metric_crs).to_crs("EPSG:4326").iloc[0]

    nodes = {
        str(node): [round(float(data["x"]), 7), round(float(data["y"]), 7)]
        for node, data in graph.nodes(data=True)
    }
    adjacency: dict[str, list[dict[str, Any]]] = {node: [] for node in nodes}
    blocked_count = 0
    for u, v, key, data in graph.edges(keys=True, data=True):
        blocked = bool(edges_metric.loc[(u, v, key)].geometry.intersects(current_flood))
        blocked_count += int(blocked)
        length = round(float(data.get("length", 0.0)), 1)
        # Conservative urban demo speed. Distance is authoritative; duration
        # remains an estimate until a production traffic provider is connected.
        travel_time = round(length / (15_000 / 3_600), 1)
        adjacency[str(u)].append(
            {
                "to": str(v),
                "lengthM": length,
                "travelTimeS": travel_time,
                "blocked": blocked,
                "coordinates": oriented_coordinates(graph, u, v, data),
            }
        )

    risk_feature = {
        "type": "Feature",
        "properties": {
            "layer": "risk_zone",
            "risk_level": "CURRENT",
            "scenario": "HINNAMNOR_REPLAY_SYNTHETIC",
            "disclaimer": "Demo impact area; not a surveyed 2022 flood boundary.",
        },
        "geometry": mapping(current_flood_wgs84),
    }
    bundle = {
        "metadata": {
            "scenario": "hinnamnor",
            "blockedEdgeCount": blocked_count,
            "forecastHorizonMinutes": 60,
            "disclaimer": (
                "Synthetic Hinnamnor replay impact area and OpenStreetMap roads. "
                "Not a safety guarantee; follow official alerts and road controls."
            ),
        },
        "nodes": nodes,
        "adjacency": adjacency,
        "riskZones": [risk_feature],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    args.scenario_output.parent.mkdir(parents=True, exist_ok=True)
    args.scenario_output.write_text(
        json.dumps({"type": "FeatureCollection", "features": [risk_feature]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "nodes": len(nodes), "edges": sum(map(len, adjacency.values())), "blocked": blocked_count}))


if __name__ == "__main__":
    main()
