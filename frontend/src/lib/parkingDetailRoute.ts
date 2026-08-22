import { distanceInMeters } from "./localParking";
import type { ParkingPlace } from "../types/parking";
import type { FloodAwareRoute, Position } from "../types/routing";

const DANGER_ROUTE_FRACTION = 0.4;

function positionToCoordinate([longitude, latitude]: Position) {
  return { latitude, longitude };
}

function routeDistance(path: Position[]) {
  return path.slice(1).reduce((total, position, index) => (
    total + distanceInMeters(positionToCoordinate(path[index]), positionToCoordinate(position))
  ), 0);
}

function reversedApproach(path: Position[], destination: ParkingPlace) {
  const lastApproachIndex = Math.max(1, Math.min(path.length - 1, Math.round((path.length - 1) * DANGER_ROUTE_FRACTION)));
  const approach = path.slice(0, lastApproachIndex + 1).reverse();
  const destinationPosition: Position = [destination.longitude, destination.latitude];

  if (distanceInMeters(positionToCoordinate(approach.at(-1)!), destination) > 3) {
    approach.push(destinationPosition);
  } else {
    approach[approach.length - 1] = destinationPosition;
  }

  return approach;
}

/**
 * Builds the fixed historical/demo approach to the selected dangerous parking lot.
 * Replace this adapter with an arbitrary origin/destination routing API response
 * when the backend routing contract is connected.
 */
export function buildDangerParkingRoute(
  evacuationRoute: FloodAwareRoute,
  destination: ParkingPlace,
): FloodAwareRoute {
  const lowerRiskPath = reversedApproach(evacuationRoute.lowerRiskPath, destination);
  const baselinePath = reversedApproach(evacuationRoute.baselinePath, destination);
  const origin = positionToCoordinate(lowerRiskPath[0]);
  const distanceMeters = Math.round(routeDistance(lowerRiskPath));

  return {
    ...evacuationRoute,
    origin,
    destination: {
      ...destination,
      safetyVerified: false,
    },
    baselinePath,
    lowerRiskPath,
    distanceMeters,
    estimatedDriveMinutes: Math.max(1, Math.ceil(distanceMeters / 250)),
    baselineDistanceMeters: Math.round(routeDistance(baselinePath)),
    disclaimer: `${evacuationRoute.disclaimer} Dangerous-place detail route preview.`,
  };
}
