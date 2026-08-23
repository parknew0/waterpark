import type { Coordinate, ParkingPlace } from "../types/parking";
import type { FloodAwareRoute } from "../types/routing";

export async function fetchLiveDrivingRoute(
  origin: Coordinate,
  destination: ParkingPlace,
): Promise<FloodAwareRoute> {
  const response = await fetch("/api/flood-route", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ scenario: "hinnamnor", origin, destination }),
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
    candidatesAwayFromOrigin.map((candidate) => fetchLiveDrivingRoute(origin, candidate)),
  );
  const routes = results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
  if (routes.length === 0) throw new Error("Unable to calculate a route to a safe parking candidate.");
  return routes.reduce((nearest, route) => (
    route.distanceMeters < nearest.distanceMeters ? route : nearest
  ));
}
