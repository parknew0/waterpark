import type { Coordinate, ParkingPlace } from "../types/parking";
import type { FloodAwareRoute, Position } from "../types/routing";

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

export async function fetchLiveDrivingRoute(
  origin: Coordinate,
  destination: ParkingPlace,
  context: FloodAwareRoute,
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
    ...context,
    origin,
    destination: { ...destination, safetyVerified: true },
    baselinePath: path,
    lowerRiskPath: path,
    distanceMeters: route.distance,
    estimatedDriveMinutes: Math.max(1, Math.ceil(route.duration / 60)),
    baselineDistanceMeters: route.distance,
    generatedAt: new Date().toISOString(),
    disclaimer: `${context.disclaimer} Live road geometry: OSRM/OpenStreetMap.`,
  };
}
