import type { Coordinate } from "./parking";

export type Position = [longitude: number, latitude: number];

export interface RiskZone {
  level: "HIGH" | "VERY_HIGH";
  polygons: Position[][];
}

export interface FloodAwareRoute {
  origin: Coordinate;
  destination: Coordinate & {
    id: string;
    name: string;
    address: string;
    safetyVerified: boolean;
  };
  baselinePath: Position[];
  lowerRiskPath: Position[];
  riskZones: RiskZone[];
  distanceMeters: number;
  baselineDistanceMeters: number;
  disclaimer: string;
  generatedAt: string;
}
