/**
 * Response shape of POST /api/flood-risk.
 *
 * Two fields carry meaning that is easy to lose in the UI and expensive to
 * get wrong.
 *
 * `surveyStatus` separates "we looked and found little risk" from "nobody
 * ever surveyed here". Incheon holds 69,142 basement buildings and exactly
 * one flood overlap, because only 144 polygons were ever surveyed there —
 * not because it is dry. NOT_SURVEYED must never render as safe.
 *
 * `riskScore` orders locations; it is not a probability. It was validated
 * with PR-AUC, which measures ranking, and was never calibrated against
 * observed frequencies. Render the level and the evidence, never a percent.
 */

export type SurveyStatus = "SURVEYED" | "NOT_SURVEYED";

export type RiskLevel =
  | "VERY_HIGH"
  | "HIGH"
  | "MODERATE"
  | "LOW"
  | "VERY_LOW"
  | "UNKNOWN";

/** Official KMA 호우특보 levels. Not learned from our data — see docs/06. */
export type RainWarningLevel = "극한호우" | "호우경보" | "호우주의보" | "없음";

export type AlertLevel =
  | "EVACUATE"
  | "PREPARE"
  | "WATCH"
  | "CALM"
  | "UNKNOWN";

/** Raw measurements behind the alert, so the UI can phrase them its own way. */
export interface TerrainEvidence {
  /** Height above the lowest ground within 500 m. */
  relativeElevationM?: number;
  /** Height above the nearest 국가하천 water surface. */
  elevationAboveNationalRiverM?: number;
  /** Distance to the nearest surveyed flood polygon. */
  distanceToFloodTraceM?: number;
}

export interface Terrain {
  surveyStatus: SurveyStatus;
  riskLevel: RiskLevel;
  /** Ranking score in [0, 1], or null when unsurveyed. Never a probability. */
  riskScore: number | null;
  /** Rain level at which this terrain warrants action. */
  rainTrigger?: RainWarningLevel;
  evidence: TerrainEvidence;
  note?: string;
}

/** Why a reading is missing. Present only when `available` is false. */
export type RainfallUnavailableReason =
  | "NO_API_KEY"
  | "FETCH_FAILED"
  | "NO_DATA"
  | "NO_STATION";

/**
 * Observed rainfall at the nearest gauge.
 *
 * `available: false` means the reading is unknown, never that it is dry. The
 * alert degrades to UNKNOWN in that case rather than CALM, and any UI showing
 * a number must show a placeholder rather than a zero.
 */
export interface Rainfall {
  available: boolean;
  reason?: RainfallUnavailableReason;
  /** Hour the reading covers, KST, `YYYYMMDDHH00`. */
  observedHourKst?: string;
  stationId?: string;
  stationDistanceKm?: number;
  mm1h?: number | null;
  mm3h?: number | null;
  mm12h?: number | null;
  /** How many of the 12 hourly observations came back. */
  hoursCollected?: number;
  warningLevel?: RainWarningLevel;
}

export interface Alert {
  level: AlertLevel;
  headline: string;
  /** Complete sentences, already assembled server-side. */
  reasons: string[];
}

export interface NearbyParking {
  pnu: string;
  lon: number;
  lat: number;
  use: string;
  ugFloors: number;
  approvalYear: string;
  distanceM: number;
}

export interface DataQuality {
  labelMeaning: "SURFACE_FLOOD_TRACE";
  floodSurveyPeriod: string;
  disclaimer: string;
}

export interface FloodRiskResponse {
  location: { lat: number; lon: number };
  terrain: Terrain;
  rainfall: Rainfall;
  alert: Alert;
  nearbyUndergroundParking: NearbyParking[];
  dataQuality: DataQuality;
}

/**
 * Request body.
 *
 * `lat` and `lon` are the whole contract; the app sends nothing else. Every
 * other field has a server-side default, so omitting them asks for the same
 * thing while leaving the choice with the side that owns it. `nearbyParking`
 * stays declared because the endpoint still honours it if a caller ever needs
 * a different radius.
 */
export interface FloodRiskRequest {
  lat: number;
  lon: number;
  /** Defaults to `{ include: true, radiusM: 1000, limit: 5 }` when omitted. */
  nearbyParking?: {
    include?: boolean;
    radiusM?: number;
    limit?: number;
  };
}

export interface FloodRiskError {
  error: string;
  code: "BAD_REQUEST" | "OUT_OF_RANGE";
}
