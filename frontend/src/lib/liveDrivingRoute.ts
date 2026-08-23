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
