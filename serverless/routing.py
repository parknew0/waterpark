"""Dependency-free dynamic flood-aware routing for the demo Lambda."""

from __future__ import annotations

import heapq
import json
import math
import os
from pathlib import Path
from typing import Any

ROUTING_DIR = Path(os.environ.get("ROUTING_DIR", Path(__file__).parent / "routing"))
MAX_SNAP_DISTANCE_M = 3_000.0

_ROUTING_STATE: dict[str, dict[str, Any]] = {}


def load_scenario(name: str) -> dict[str, Any]:
    if name in _ROUTING_STATE:
        return _ROUTING_STATE[name]
    if name != "hinnamnor":
        raise ValueError("지원하지 않는 라우팅 시나리오입니다")
    payload = json.loads((ROUTING_DIR / f"{name}.json").read_text(encoding="utf-8"))
    _ROUTING_STATE[name] = payload
    return payload


def distance_m(a: list[float], b: list[float]) -> float:
    lon_scale = 88_000.0
    lat_scale = 111_000.0
    return math.hypot((a[0] - b[0]) * lon_scale, (a[1] - b[1]) * lat_scale)


def nearest_node(nodes: dict[str, list[float]], coordinate: list[float]) -> tuple[str, float]:
    node, distance = min(
        ((node_id, distance_m(position, coordinate)) for node_id, position in nodes.items()),
        key=lambda item: item[1],
    )
    if distance > MAX_SNAP_DISTANCE_M:
        raise ValueError("시연 도로망에서 너무 먼 좌표입니다")
    return node, distance


def dijkstra(
    adjacency: dict[str, list[dict[str, Any]]],
    start: str,
    end: str,
    avoid_blocked: bool,
) -> tuple[list[dict[str, Any]], float, float, int]:
    queue: list[tuple[float, str]] = [(0.0, start)]
    costs = {start: 0.0}
    previous: dict[str, tuple[str, dict[str, Any]]] = {}
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != costs.get(node):
            continue
        if node == end:
            break
        for edge in adjacency.get(node, []):
            if avoid_blocked and edge["blocked"]:
                continue
            next_node = edge["to"]
            next_cost = cost + float(edge["lengthM"])
            if next_cost >= costs.get(next_node, math.inf):
                continue
            costs[next_node] = next_cost
            previous[next_node] = (node, edge)
            heapq.heappush(queue, (next_cost, next_node))
    if end not in costs:
        raise ValueError("침수 영향권을 제외한 도로 경로를 찾지 못했습니다")

    edges: list[dict[str, Any]] = []
    cursor = end
    while cursor != start:
        prior, edge = previous[cursor]
        edges.append(edge)
        cursor = prior
    edges.reverse()
    distance = sum(float(edge["lengthM"]) for edge in edges)
    duration = sum(float(edge["travelTimeS"]) for edge in edges)
    blocked_edges = sum(int(edge["blocked"]) for edge in edges)
    return edges, distance, duration, blocked_edges


def path_coordinates(edges: list[dict[str, Any]], origin: list[float], destination: list[float]) -> list[list[float]]:
    path = [origin]
    for edge in edges:
        coordinates = edge["coordinates"]
        if path[-1] == coordinates[0]:
            path.extend(coordinates[1:])
        else:
            path.extend(coordinates)
    path.append(destination)
    return path


def parse_coordinate(value: Any, label: str) -> list[float]:
    try:
        latitude = float(value["latitude"])
        longitude = float(value["longitude"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{label} 위도·경도가 필요합니다") from None
    if not (124.0 <= longitude <= 132.0 and 33.0 <= latitude <= 39.0):
        raise ValueError(f"{label}가 대한민국 범위 밖입니다")
    return [longitude, latitude]


def calculate_route(request: dict[str, Any]) -> dict[str, Any]:
    scenario = str(request.get("scenario") or "hinnamnor")
    state = load_scenario(scenario)
    origin = parse_coordinate(request.get("origin"), "출발지")
    destination = parse_coordinate(request.get("destination"), "목적지")
    origin_node, origin_snap_m = nearest_node(state["nodes"], origin)
    destination_node, destination_snap_m = nearest_node(state["nodes"], destination)

    baseline_edges, baseline_distance, _, baseline_blocked = dijkstra(
        state["adjacency"], origin_node, destination_node, avoid_blocked=False
    )
    lower_edges, lower_distance, lower_duration, lower_blocked = dijkstra(
        state["adjacency"], origin_node, destination_node, avoid_blocked=True
    )
    destination_input = request.get("destination") or {}
    risk_zones = [
        {
            "level": feature["properties"]["risk_level"],
            "polygons": [feature["geometry"]["coordinates"][0]],
        }
        for feature in state["riskZones"]
    ]
    avoided = baseline_blocked > 0 and lower_blocked == 0
    return {
        "origin": {"latitude": origin[1], "longitude": origin[0]},
        "destination": {
            "latitude": destination[1],
            "longitude": destination[0],
            "id": str(destination_input.get("id") or "selected-parking"),
            "name": str(destination_input.get("name") or "Selected Parking"),
            "address": str(destination_input.get("address") or "Address unavailable"),
            "safetyVerified": False,
        },
        "baselinePath": path_coordinates(baseline_edges, origin, destination),
        "lowerRiskPath": path_coordinates(lower_edges, origin, destination),
        "riskZones": risk_zones,
        "distanceMeters": round(lower_distance, 1),
        "estimatedDriveMinutes": max(1, math.ceil(lower_duration / 60.0)),
        "forecastHorizonMinutes": int(state["metadata"]["forecastHorizonMinutes"]),
        "baselineDistanceMeters": round(baseline_distance, 1),
        "disclaimer": state["metadata"]["disclaimer"],
        "generatedAt": "runtime",
        "routeDecision": {
            "avoidedCurrentFlood": avoided,
            "baselineBlockedEdgeCount": baseline_blocked,
            "lowerRiskBlockedEdgeCount": lower_blocked,
            "scenarioBlockedEdgeCount": int(state["metadata"]["blockedEdgeCount"]),
            "originSnapDistanceM": round(origin_snap_m, 1),
            "destinationSnapDistanceM": round(destination_snap_m, 1),
        },
    }


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    try:
        body = event.get("body") or "{}"
        request = json.loads(body) if isinstance(body, str) else body
        return {
            "statusCode": 200,
            "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
            "body": json.dumps(calculate_route(request), ensure_ascii=False),
        }
    except (FileNotFoundError, ValueError) as exc:
        return {
            "statusCode": 422,
            "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
            "body": json.dumps({"error": str(exc), "code": "ROUTE_UNAVAILABLE"}, ensure_ascii=False),
        }
