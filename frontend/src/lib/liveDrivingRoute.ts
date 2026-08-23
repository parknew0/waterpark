import type { Coordinate, ParkingPlace } from "../types/parking";
import type { FloodAwareRoute, Position } from "../types/routing";

export type DrivingRouteScenario = "current" | "hinnamnor";

interface OsrmRouteResponse {
  code: string;
  routes?: Array<{
    distance: number;
    duration: number;
    geometry: { coordinates: Position[] };
  }>;
}

function connectEndpoints(path: Position[], origin: Coordinate, destination: Coordinate) {
  const originPosition: Position = [origin.longitude, origin.latitude];
  const destinationPosition: Position = [destination.longitude, destination.latitude];
  if (path.length === 0) return [originPosition, destinationPosition];
  return [originPosition, ...path, destinationPosition];
}

async function fetchCurrentDrivingRoute(
  origin: Coordinate,
  destination: ParkingPlace,
): Promise<FloodAwareRoute> {
  const coordinates = `${origin.longitude},${origin.latitude};${destination.longitude},${destination.latitude}`;
  const url = new URL(`https://router.project-osrm.org/route/v1/driving/${coordinates}`);
  url.searchParams.set("overview", "full");
  url.searchParams.set("geometries", "geojson");
  url.searchParams.set("steps", "false");

  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`OSRM route response: ${response.status}`);
  const payload = await response.json() as OsrmRouteResponse;
  const route = payload.routes?.[0];
  if (payload.code !== "Ok" || !route) throw new Error(`OSRM route failed: ${payload.code}`);

  const path = connectEndpoints(route.geometry.coordinates, origin, destination);
  return {
    origin,
    destination: { ...destination, safetyVerified: false },
    baselinePath: path,
    lowerRiskPath: path,
    riskZones: [],
    distanceMeters: route.distance,
    estimatedDriveMinutes: Math.max(1, Math.ceil(route.duration / 60)),
    forecastHorizonMinutes: 60,
    baselineDistanceMeters: route.distance,
    disclaimer: "Current Safe preview uses live OSRM/OpenStreetMap road geometry; flood avoidance is not active.",
    generatedAt: new Date().toISOString(),
  };
}

export async function fetchLiveDrivingRoute(
  origin: Coordinate,
  destination: ParkingPlace,
  scenario: DrivingRouteScenario = "current",
): Promise<FloodAwareRoute> {
  if (scenario === "current") return fetchCurrentDrivingRoute(origin, destination);
  const response = await fetch("/api/flood-route", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ scenario, origin, destination }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { error?: string };
    throw new Error(payload.error ?? `Flood-aware route response: ${response.status}`);
  }
  return response.json() as Promise<FloodAwareRoute>;
}

export async function fetchNearestSafeDrivingRoute(
  origin: Coordinate,
  candidates: ParkingPlace[],
  scenario: DrivingRouteScenario = "current",
): Promise<FloodAwareRoute> {
  const candidatesAwayFromOrigin = candidates.filter((candidate) => {
    const eastWestMeters = (candidate.longitude - origin.longitude) * 88_000;
    const northSouthMeters = (candidate.latitude - origin.latitude) * 111_000;
    return Math.hypot(eastWestMeters, northSouthMeters) >= 25;
  });
  if (candidatesAwayFromOrigin.length === 0) {
    throw new Error("No safe parking candidates are available away from the current car location.");
  }
  const results = await Promise.allSettled(
    candidatesAwayFromOrigin.map((candidate) => fetchLiveDrivingRoute(origin, candidate, scenario)),
  );
  const routes = results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
  if (routes.length === 0) throw new Error("Unable to calculate a route to a safe parking candidate.");
  return routes.reduce((nearest, route) => (
    route.distanceMeters < nearest.distanceMeters ? route : nearest
  ));
}
