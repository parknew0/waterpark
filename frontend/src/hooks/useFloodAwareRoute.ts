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
    baselinePath: baseline.geometry.coordinates as Position[],
    lowerRiskPath: lowerRisk.geometry.coordinates as Position[],
    riskZones: features.flatMap((feature) => {
      if (feature.properties.layer !== "risk_zone") return [];
      const zone = toRiskZone(feature);
      return zone ? [zone] : [];
    }),
    distanceMeters: Number(lowerRisk.properties.distance_m ?? 0),
    baselineDistanceMeters: Number(baseline.properties.distance_m ?? 0),
    disclaimer: String(payload.metadata?.disclaimer ?? "실제 재난 안내와 도로 통제를 함께 확인하세요."),
    generatedAt: String(payload.metadata?.generated_at ?? ""),
  };
}

export function useFloodAwareRoute(enabled: boolean) {
  const [route, setRoute] = useState<FloodAwareRoute>();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || route) return;
    const controller = new AbortController();
    fetch("/data/pohang-flood-aware-route.geojson", { signal: controller.signal })
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
  }, [enabled, route]);

  return { route, error };
}
