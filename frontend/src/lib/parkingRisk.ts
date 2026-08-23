import type { ParkingPlace } from "../types/parking";

export type ParkingRiskBranch = "danger" | "safe";

export interface ParkingRiskSelectionContext {
  dangerParkingId: string;
  safeParkingIds: string[];
}

/**
 * UI-facing boundary for the parking risk API.
 * Replace this deterministic demo adapter when the backend request/response
 * contract is finalized; the map and detail views do not need to change.
 */
export async function resolveParkingRiskBranch(
  place: ParkingPlace,
  context: ParkingRiskSelectionContext,
): Promise<ParkingRiskBranch> {
  if (context.safeParkingIds.includes(place.id)) return "safe";
  if (place.id === context.dangerParkingId) return "danger";
  return "danger";
}
