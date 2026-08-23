import { useEffect, useState } from "react";
import type { FloodAwareRoute, Position, RiskZone } from "../types/routing";

interface GeoJsonFeature {
  geometry: { type: string; coordinates: unknown };
  properties: Record<string, unknown>;
}

interface RouteGeoJson {
  metadata?: Record<string, unknown>;
  features?: GeoJsonFeature[];
}

function featureByLayer(features: GeoJsonFeature[], layer: string) {
  return features.find((feature) => feature.properties.layer === layer);
}

function connectRouteEndpoints(path: Position[], origin: Position, destination: Position) {
  if (path.length === 0) return [origin, destination];
  const squaredDistance = (a: Position, b: Position) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
  const oriented = squaredDistance(path[0], origin) <= squaredDistance(path.at(-1)!, origin)
    ? [...path]
    : [...path].reverse();
  if (squaredDistance(oriented[0], origin) > 1e-12) oriented.unshift(origin);
  else oriented[0] = origin;
  if (squaredDistance(oriented.at(-1)!, destination) > 1e-12) oriented.push(destination);
  else oriented[oriented.length - 1] = destination;
  return oriented;
}

function toRiskZone(feature: GeoJsonFeature): RiskZone | null {
  const level = feature.properties.risk_level;
  if (level !== "HIGH" && level !== "VERY_HIGH" && level !== "CURRENT") return null;
  if (feature.geometry.type === "Polygon") {
    return { level, polygons: feature.geometry.coordinates as Position[][] };
  }
  if (feature.geometry.type === "MultiPolygon") {
    return {
      level,
      polygons: (feature.geometry.coordinates as Position[][][]).flatMap((polygon) => polygon),
    };
  }
  return null;
}

function parseRoute(payload: RouteGeoJson): FloodAwareRoute {
  const features = payload.features ?? [];
  const origin = featureByLayer(features, "origin");
  const destination = featureByLayer(features, "destination");
  const baseline = featureByLayer(features, "baseline_route");
  const lowerRisk = featureByLayer(features, "lower_risk_route");
  if (!origin || !destination || !baseline || !lowerRisk) {
    throw new Error("경로 GeoJSON에 필수 레이어가 없습니다.");
  }
  const [originLongitude, originLatitude] = origin.geometry.coordinates as Position;
  const [destinationLongitude, destinationLatitude] = destination.geometry.coordinates as Position;
  const originPosition: Position = [originLongitude, originLatitude];
  const destinationPosition: Position = [destinationLongitude, destinationLatitude];
  const distanceMeters = Number(lowerRisk.properties.distance_m ?? 0);
  const travelTimeSeconds = Number(lowerRisk.properties.travel_time_s ?? 0);
  return {
    origin: { latitude: originLatitude, longitude: originLongitude },
    destination: {
      latitude: destinationLatitude,
      longitude: destinationLongitude,
      id: String(destination.properties.id ?? "route-destination"),
      name: String(destination.properties.name ?? "대피 주차장 후보"),
      address: String(destination.properties.address ?? "주소 정보 없음"),
      safetyVerified: destination.properties.safety_verified === true,
    },
    baselinePath: connectRouteEndpoints(baseline.geometry.coordinates as Position[], originPosition, destinationPosition),
    lowerRiskPath: connectRouteEndpoints(lowerRisk.geometry.coordinates as Position[], originPosition, destinationPosition),
    riskZones: features.flatMap((feature) => {
      if (feature.properties.layer !== "risk_zone") return [];
      const zone = toRiskZone(feature);
      return zone ? [zone] : [];
    }),
    distanceMeters,
    estimatedDriveMinutes: Math.max(1, Math.ceil(travelTimeSeconds > 0 ? travelTimeSeconds / 60 : distanceMeters / 250)),
    forecastHorizonMinutes: Number(payload.metadata?.forecast_horizon_minutes ?? 60),
    baselineDistanceMeters: Number(baseline.properties.distance_m ?? 0),
    disclaimer: String(payload.metadata?.disclaimer ?? "실제 재난 안내와 도로 통제를 함께 확인하세요."),
    generatedAt: String(payload.metadata?.generated_at ?? ""),
  };
}

export function useFloodAwareRoute(enabled: boolean, dataUrl = "/data/pohang-flood-aware-route.geojson") {
  const [route, setRoute] = useState<FloodAwareRoute>();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || route) return;
    const controller = new AbortController();
    fetch(dataUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`경로 데이터 응답 오류: ${response.status}`);
        return response.json() as Promise<RouteGeoJson>;
      })
      .then((payload) => setRoute(parseRoute(payload)))
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "대피 경로를 불러오지 못했습니다.");
      });
    return () => controller.abort();
  }, [dataUrl, enabled, route]);

  return { route, error };
}
