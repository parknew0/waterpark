import type { ParkingPlace } from "../types/parking";

export type ParkingRiskBranch = "danger" | "safe";

export interface ParkingRiskSelectionContext {
  dangerParkingId: string;
  lowerRiskParkingId: string;
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
  if (place.id === context.lowerRiskParkingId) return "safe";
  if (place.id === context.dangerParkingId) return "danger";
  throw new Error("No flood-risk assessment is available for the selected parking lot.");
}
