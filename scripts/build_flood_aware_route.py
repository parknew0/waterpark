#!/usr/bin/env python3
"""Build a reproducible flood-risk-aware driving-route demo GeoJSON.

This is a decision-support prototype. The local risk input describes static
surface-flood susceptibility around buildings; it is not a live road-closure
feed and it does not prove that any destination is safe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
from shapely.geometry import LineString, Point, mapping
from shapely.ops import unary_union

from data_paths import (
    OUTPUTS_ROUTING,
    PROCESSED_ML_PREDICTIONS,
    PROCESSED_PARKING,
    RAW_OSM_CACHE,
    RAW_OSM_ROUTING,
    ROOT,
)

DEFAULT_RISK = PROCESSED_ML_PREDICTIONS / "gyeongbuk_underground_parking_risk.csv"
DEFAULT_PARKING = PROCESSED_PARKING / "gyeongbuk_parking_seed.csv"
DEFAULT_OUTPUT = OUTPUTS_ROUTING / "pohang-postech-flood-aware-route.geojson"
DEFAULT_FRONTEND_OUTPUT = ROOT / "frontend" / "public" / "data" / "pohang-flood-aware-route.geojson"
DEFAULT_GRAPH = RAW_OSM_ROUTING / "pohang-postech-drive.graphml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin-lat", type=float, default=36.014)
    parser.add_argument("--origin-lon", type=float, default=129.325)
    parser.add_argument("--radius-m", type=int, default=2_500)
    parser.add_argument("--risk-buffer-m", type=float, default=120.0)
    parser.add_argument("--high-penalty", type=float, default=5.0)
    parser.add_argument("--very-high-penalty", type=float, default=12.0)
    parser.add_argument("--candidate-limit", type=int, default=25)
    parser.add_argument("--risk-csv", type=Path, default=DEFAULT_RISK)
    parser.add_argument("--parking-csv", type=Path, default=DEFAULT_PARKING)
    parser.add_argument("--graphml", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--current-flood-geojson", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--frontend-output", type=Path, default=DEFAULT_FRONTEND_OUTPUT)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_or_download_graph(args: argparse.Namespace) -> nx.MultiDiGraph:
    ox.settings.use_cache = True
    ox.settings.cache_folder = RAW_OSM_CACHE
    args.graphml.parent.mkdir(parents=True, exist_ok=True)
    if args.graphml.exists():
        return ox.load_graphml(args.graphml)

    graph = ox.graph.graph_from_point(
        (args.origin_lat, args.origin_lon),
        dist=args.radius_m,
        network_type="drive",
        simplify=True,
        retain_all=True,
    )
    ox.save_graphml(graph, args.graphml)
    return graph


def edge_geometry(graph: nx.MultiDiGraph, u: int, v: int, data: dict[str, Any]) -> LineString:
    geometry = data.get("geometry")
    if geometry is not None:
        return geometry
    return LineString([(graph.nodes[u]["x"], graph.nodes[u]["y"]), (graph.nodes[v]["x"], graph.nodes[v]["y"])])


def select_edge(graph: nx.MultiDiGraph, u: int, v: int, weight: str) -> tuple[int, dict[str, Any]]:
    candidates = graph.get_edge_data(u, v)
    if not candidates:
        raise nx.NetworkXNoPath(f"Missing route edge {u}->{v}")
    return min(candidates.items(), key=lambda item: float(item[1].get(weight, item[1].get("length", 1.0))))


def route_geometry(graph: nx.MultiDiGraph, nodes: list[int], weight: str) -> LineString:
    coordinates: list[tuple[float, float]] = []
    for u, v in zip(nodes, nodes[1:]):
        _, data = select_edge(graph, u, v, weight)
        segment = list(edge_geometry(graph, u, v, data).coords)
        origin_xy = (float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"]))
        if Point(segment[-1]).distance(Point(origin_xy)) < Point(segment[0]).distance(Point(origin_xy)):
            segment.reverse()
        coordinates.extend(segment if not coordinates else segment[1:])
    return LineString(coordinates)


def route_metrics(graph: nx.MultiDiGraph, nodes: list[int], weight: str) -> dict[str, float]:
    metrics = {"distance_m": 0.0, "high_exposure_m": 0.0, "very_high_exposure_m": 0.0, "risk_cost": 0.0}
    for u, v in zip(nodes, nodes[1:]):
        _, data = select_edge(graph, u, v, weight)
        for key in metrics:
            fallback = data.get("length", 0.0) if key in {"distance_m", "risk_cost"} else 0.0
            source_key = "length" if key == "distance_m" else key
            metrics[key] += float(data.get(source_key, fallback))
    return {key: round(value, 1) for key, value in metrics.items()}


def add_risk_costs(
    graph: nx.MultiDiGraph,
    risk_csv: Path,
    buffer_m: float,
    high_penalty: float,
    very_high_penalty: float,
    current_flood_geojson: Path | None,
) -> tuple[nx.MultiDiGraph, Any, Any, str, int]:
    nodes, edges = ox.graph_to_gdfs(graph)
    metric_crs = edges.estimate_utm_crs()
    edges_metric = edges.to_crs(metric_crs)

    risk = pd.read_csv(risk_csv, usecols=["longitude", "latitude", "static_risk"])
    risk = risk[risk["static_risk"].isin(["HIGH", "VERY_HIGH"])].dropna()
    risk_gdf = gpd.GeoDataFrame(
        risk,
        geometry=gpd.points_from_xy(risk["longitude"], risk["latitude"]),
        crs="EPSG:4326",
    ).to_crs(metric_crs)
    search_area = unary_union(edges_metric.geometry).envelope.buffer(buffer_m)
    risk_gdf = risk_gdf[risk_gdf.intersects(search_area)]

    very_high = unary_union(risk_gdf.loc[risk_gdf["static_risk"] == "VERY_HIGH", "geometry"].buffer(buffer_m).tolist())
    high_all = unary_union(risk_gdf.loc[risk_gdf["static_risk"] == "HIGH", "geometry"].buffer(buffer_m).tolist())
    high_only = high_all.difference(very_high) if not high_all.is_empty else high_all

    blocked_union = None
    if current_flood_geojson:
        blocked = gpd.read_file(current_flood_geojson).to_crs(metric_crs)
        blocked_union = unary_union(blocked.geometry.tolist())

    routed_graph = graph.copy()
    blocked_edges: list[tuple[int, int, int]] = []
    for index, row in edges_metric.iterrows():
        u, v, key = index
        geometry = row.geometry
        high_exposure = geometry.intersection(high_only).length if not high_only.is_empty else 0.0
        very_high_exposure = geometry.intersection(very_high).length if not very_high.is_empty else 0.0
        base_length = float(routed_graph[u][v][key].get("length", geometry.length))
        routed_graph[u][v][key]["high_exposure_m"] = high_exposure
        routed_graph[u][v][key]["very_high_exposure_m"] = very_high_exposure
        routed_graph[u][v][key]["risk_cost"] = (
            base_length + high_exposure * high_penalty + very_high_exposure * very_high_penalty
        )
        if blocked_union is not None and geometry.intersects(blocked_union):
            blocked_edges.append((u, v, key))
    routed_graph.remove_edges_from(blocked_edges)
    return routed_graph, high_only, very_high, str(metric_crs), len(blocked_edges)


def choose_destination(
    graph: nx.MultiDiGraph,
    parking_csv: Path,
    origin_node: int,
    origin: Point,
    metric_crs: str,
    high_risk: Any,
    very_high_risk: Any,
    candidate_limit: int,
) -> tuple[pd.Series, list[int], list[int], int]:
    parking = pd.read_csv(parking_csv).dropna(subset=["latitude", "longitude"])
    parking_gdf = gpd.GeoDataFrame(
        parking,
        geometry=gpd.points_from_xy(parking["longitude"], parking["latitude"]),
        crs="EPSG:4326",
    ).to_crs(metric_crs)
    origin_metric = gpd.GeoSeries([origin], crs="EPSG:4326").to_crs(metric_crs).iloc[0]
    parking_gdf["origin_distance_m"] = parking_gdf.geometry.distance(origin_metric)
    parking_gdf = parking_gdf.sort_values("origin_distance_m")
    parking_gdf = parking_gdf[parking_gdf["origin_distance_m"] <= 5_000]
    if not high_risk.is_empty:
        parking_gdf = parking_gdf[~parking_gdf.intersects(high_risk)]
    if not very_high_risk.is_empty:
        parking_gdf = parking_gdf[~parking_gdf.intersects(very_high_risk)]
    parking_gdf = parking_gdf.head(candidate_limit)

    best: tuple[float, pd.Series, list[int], list[int], int] | None = None
    for _, candidate in parking_gdf.iterrows():
        destination_node = ox.distance.nearest_nodes(graph, X=float(candidate["longitude"]), Y=float(candidate["latitude"]))
        try:
            lower_risk = nx.shortest_path(graph, origin_node, destination_node, weight="risk_cost", method="dijkstra")
            baseline = nx.shortest_path(graph, origin_node, destination_node, weight="length", method="dijkstra")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        metrics = route_metrics(graph, lower_risk, "risk_cost")
        score = metrics["risk_cost"]
        if best is None or score < best[0]:
            best = (score, candidate, lower_risk, baseline, destination_node)
    if best is None:
        raise RuntimeError("No reachable parking candidate remained after risk filtering.")
    return best[1], best[2], best[3], best[4]


def make_feature(geometry: Any, **properties: Any) -> dict[str, Any]:
    return {"type": "Feature", "geometry": mapping(geometry), "properties": properties}


def first_text(*values: Any) -> str:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return str(value).strip()
    return "주소 정보 없음"


def main() -> None:
    args = parse_args()
    for input_path in (args.risk_csv, args.parking_csv):
        if not input_path.exists():
            raise FileNotFoundError(input_path)

    graph = load_or_download_graph(args)
    origin = Point(args.origin_lon, args.origin_lat)
    origin_node = ox.distance.nearest_nodes(graph, X=args.origin_lon, Y=args.origin_lat)
    graph, high_risk, very_high_risk, metric_crs, blocked_count = add_risk_costs(
        graph,
        args.risk_csv,
        args.risk_buffer_m,
        args.high_penalty,
        args.very_high_penalty,
        args.current_flood_geojson,
    )
    destination, lower_nodes, baseline_nodes, _ = choose_destination(
        graph,
        args.parking_csv,
        origin_node,
        origin,
        metric_crs,
        high_risk,
        very_high_risk,
        args.candidate_limit,
    )

    lower_geometry = route_geometry(graph, lower_nodes, "risk_cost")
    baseline_geometry = route_geometry(graph, baseline_nodes, "length")
    lower_metrics = route_metrics(graph, lower_nodes, "risk_cost")
    baseline_metrics = route_metrics(graph, baseline_nodes, "length")
    to_wgs84 = lambda geometry: gpd.GeoSeries([geometry], crs=metric_crs).to_crs("EPSG:4326").iloc[0]

    generated_at = datetime.now(timezone.utc).isoformat()
    features = [
        make_feature(origin, layer="origin", label="Demo origin near POSTECH"),
        make_feature(
            Point(float(destination["longitude"]), float(destination["latitude"])),
            layer="destination",
            id=str(destination["entity_id"]),
            name=str(destination["name"]),
            address=first_text(destination["road_address"], destination["lot_address"]),
            parking_type=str(destination["parking_type"]),
            safety_verified=False,
        ),
        make_feature(baseline_geometry, layer="baseline_route", **baseline_metrics),
        make_feature(lower_geometry, layer="lower_risk_route", **lower_metrics),
    ]
    if not high_risk.is_empty:
        features.append(make_feature(to_wgs84(high_risk), layer="risk_zone", risk_level="HIGH"))
    if not very_high_risk.is_empty:
        features.append(make_feature(to_wgs84(very_high_risk), layer="risk_zone", risk_level="VERY_HIGH"))

    result = {
        "type": "FeatureCollection",
        "metadata": {
            "generated_at": generated_at,
            "prototype": True,
            "label": "lower-risk route candidate",
            "disclaimer": "Static surface-flood susceptibility and OSM roads only. Not a safety guarantee; follow official alerts and road controls.",
            "osm_attribution": "© OpenStreetMap contributors",
            "origin": {"latitude": args.origin_lat, "longitude": args.origin_lon},
            "parameters": {
                "radius_m": args.radius_m,
                "risk_buffer_m": args.risk_buffer_m,
                "high_penalty": args.high_penalty,
                "very_high_penalty": args.very_high_penalty,
                "candidate_limit": args.candidate_limit,
            },
            "blocked_edge_count": blocked_count,
            "limitations": [
                "risk influence radius is a demo parameter, not an official flood boundary",
                "parking destination safety_verified is false",
                "no live capacity or road-closure feed is included unless explicitly supplied",
            ],
            "inputs": {
                "risk_csv_sha256": sha256(args.risk_csv),
                "parking_csv_sha256": sha256(args.parking_csv),
            },
        },
        "features": features,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.frontend_output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    args.frontend_output.write_text(encoded + "\n", encoding="utf-8")

    manifest_path = args.output.with_suffix(".manifest.json")
    manifest = {
        "generated_at": generated_at,
        "output": str(args.output.relative_to(ROOT)),
        "frontend_output": str(args.frontend_output.relative_to(ROOT)),
        "feature_count": len(features),
        "destination": destination["name"],
        "baseline": baseline_metrics,
        "lower_risk": lower_metrics,
        "blocked_edge_count": blocked_count,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
