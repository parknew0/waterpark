import { useCallback, useEffect, useRef, useState } from "react";
import type {
  FloodRiskRequest,
  FloodRiskResponse,
  Rainfall,
  RiskLevel,
} from "../types/floodRisk";

/**
 * Ask the risk API about one point on the map.
 *
 * The endpoint is same-origin by default (`/api/flood-risk`) because the
 * Lambda sits behind the same CDN as this app. That removes CORS entirely
 * and means no second domain to buy or certify. `VITE_FLOOD_RISK_API`
 * overrides it for local work against a deployed function.
 *
 * Requests are aborted when a newer one starts. Users drag and tap around a
 * map faster than a round trip completes, and without this the last response
 * to arrive wins rather than the last one asked for.
 */

const ENDPOINT =
  import.meta.env.VITE_FLOOD_RISK_API?.trim() || "/api/flood-risk";

export interface UseFloodRiskState {
  data: FloodRiskResponse | null;
  loading: boolean;
  error: string | null;
}

export function useFloodRisk(point: { lat: number; lon: number } | null) {
  const [state, setState] = useState<UseFloodRiskState>({
    data: null,
    // A point supplied at mount means a request is already on its way, so the
    // first render should not claim to be idle.
    loading: point != null,
    error: null,
  });
  const inFlight = useRef<AbortController | null>(null);

  /**
   * Run one request and report its outcome.
   *
   * Every setState here happens inside a promise callback rather than on the
   * caller's synchronous path. That is what lets the effect below use this
   * directly: React 19 treats a synchronous setState inside an effect as a
   * cascading render, and the other hooks in this app avoid it the same way.
   */
  const run = useCallback((request: FloodRiskRequest, signal: AbortSignal) => {
    return fetch(ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
      signal,
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          setState({
            data: null,
            loading: false,
            error: payload?.error ?? "Unable to load flood risk",
          });
          return null;
        }
        setState({ data: payload as FloodRiskResponse, loading: false, error: null });
        return payload as FloodRiskResponse;
      })
      .catch((caught: unknown) => {
        // An abort is this hook superseding itself, not a failure to report.
        if (caught instanceof DOMException && caught.name === "AbortError") return null;
        setState({ data: null, loading: false, error: "Unable to load flood risk" });
        return null;
      });
  }, []);

  /**
   * Ask about a point on demand, from an event handler.
   *
   * Unlike the effect, a handler may mark the request in flight immediately,
   * which is what a tap on the map should do.
   */
  const query = useCallback(
    (request: FloodRiskRequest) => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      setState((previous) => ({ ...previous, loading: true, error: null }));
      return run(request, controller.signal);
    },
    [run],
  );

  const lat = point?.lat;
  const lon = point?.lon;

  useEffect(() => {
    if (lat == null || lon == null) return;
    const controller = new AbortController();
    inFlight.current = controller;
    // `loading` is deliberately left alone here. Blanking a reading that is
    // already on screen every time the map settles reads as a fault; keeping
    // the previous number until the new one lands does not.
    // Only the coordinate is sent. Every other field the API accepts has a
    // server-side default, and the app decides what to show from the response
    // rather than asking for a pre-filtered slice of it.
    void run({ lat, lon }, controller.signal);
    return () => controller.abort();
  }, [lat, lon, run]);

  useEffect(() => () => inFlight.current?.abort(), []);

  return { ...state, query };
}

/**
 * The home chip's rainfall text, and the label a screen reader hears.
 *
 * A failed lookup renders "--mm", never "0.0mm". This is the number a driver
 * glances at, and showing zero because the request failed states the one
 * thing that would keep someone parked through a downpour.
 */
export function formatRainfall(rainfall?: Rainfall): string {
  if (!rainfall?.available || rainfall.mm1h == null) return "--mm";
  return `${rainfall.mm1h.toFixed(1)}mm`;
}

export function rainfallAriaLabel(rainfall?: Rainfall): string {
  if (!rainfall?.available || rainfall.mm1h == null) {
    return "Rainfall data are unavailable";
  }
  return `Rainfall over the last hour: ${formatRainfall(rainfall)}`;
}

/**
 * The word that fills "<X> risk of flooding in the next 1 hour".
 *
 * UNKNOWN becomes "Unknown" rather than its list label, which reads as a
 * sentence fragment in this slot. It must never resolve to "Low": an
 * unsurveyed location is not a safe one.
 */
export function riskWord(risk?: FloodRiskResponse | null): string | undefined {
  if (!risk) return undefined;
  if (risk.terrain.riskLevel === "UNKNOWN") return "Unknown";
  return RISK_LABELS[risk.terrain.riskLevel];
}

/**
 * Which of the two badges the design has -- Warning or Safe -- fits a place.
 *
 * It reads `terrain.riskLevel`, the same field as the headline word, so the
 * badge and the sentence under it can never disagree. `alert.level` would be
 * the wrong source: it folds in today's weather, so every location reads
 * "Safe" whenever it is not raining, including ones the model ranks in the
 * top 5%.
 *
 * The split follows `rainTrigger`, which already encodes this judgement:
 * VERY_HIGH and HIGH act at the lowest rain threshold, the rest wait. Reusing
 * it keeps one decision in one place instead of inventing a second cutoff.
 *
 * UNKNOWN returns "warning". The design has no third badge, and of the two
 * available errors -- worrying someone about an unsurveyed place, or telling
 * them it is safe when nobody ever checked -- only the first is recoverable.
 */
export function riskBadge(
  risk?: FloodRiskResponse | null,
): "warning" | "safe" | undefined {
  const level = risk?.terrain.riskLevel;
  if (!level) return undefined;
  return level === "VERY_HIGH" || level === "HIGH" || level === "UNKNOWN"
    ? "warning"
    : "safe";
}

/**
 * The two bullets shown under "Here's why".
 *
 * The screens pair one terrain reason with one rainfall reason, but
 * `alert.reasons` is ordered by evidence type -- its second entry is the
 * river comparison, not rain -- so the pair is assembled here rather than
 * sliced off the front of that array.
 *
 * An unavailable reading says so instead of printing a number, for the same
 * reason the home chip shows dashes: a failed lookup is not a dry sky.
 */
export function riskBullets(
  risk?: FloodRiskResponse | null,
): string[] | undefined {
  if (!risk) return undefined;

  // Unsurveyed places still get a rain reading -- the gauge network covers the
  // country even where the flood survey does not -- so this line is real
  // everywhere. Prefer the six-hour window the design asks for, and fall back
  // to windows the API has always sent rather than printing "unavailable"
  // over data we hold.
  const { available, mm6h, mm3h, mm1h, stationDistanceKm } = risk.rainfall;
  let rain = "Rainfall could not be read from the nearest gauge";
  if (available) {
    if (mm6h != null) rain = `Rainfall over the past 6 hours: ${mm6h.toFixed(1)} mm`;
    else if (mm3h != null) rain = `Rainfall over the past 3 hours: ${mm3h.toFixed(1)} mm`;
    else if (mm1h != null) rain = `Rainfall over the past hour: ${mm1h.toFixed(1)} mm`;
    // A gauge several kilometres off can be under a different cell of the same
    // storm, so the distance is part of the reading rather than a footnote.
    if (stationDistanceKm != null && stationDistanceKm >= 3) {
      rain += ` (nearest gauge ${stationDistanceKm.toFixed(1)} km away)`;
    }
  }

  // Outside the grid there is no elevation to quote, so say what is missing
  // rather than leaving a blank where a measurement should be.
  if (risk.terrain.surveyStatus === "NOT_SURVEYED") {
    return [
      "No past flood survey covers this spot, so terrain risk is unmeasured here",
      rain,
    ];
  }

  // Every terrain reason is shown. The response carries three measurements --
  // height above the local low point, height above the nearest national river,
  // and distance to the nearest recorded flood -- and showing only the first
  // threw away two thirds of the explanation the model actually rests on.
  const terrain = risk.alert.reasons.filter(
    (line) => !line.startsWith("Current rainfall"),
  );
  if (terrain.length === 0) return undefined;
  return [...terrain, rain];
}

/**
 * Map colour per risk level.
 *
 * UNKNOWN is deliberately grey rather than green. An unsurveyed location is
 * not a low-risk location, and colouring it like one would state something
 * the data does not support.
 */
export const RISK_COLORS: Record<RiskLevel, string> = {
  VERY_HIGH: "#b3261e",
  HIGH: "#e8710a",
  MODERATE: "#f2b705",
  LOW: "#5b8c5a",
  VERY_LOW: "#3f6f8f",
  UNKNOWN: "#8a8f98",
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  VERY_HIGH: "Very high",
  HIGH: "High",
  MODERATE: "Moderate",
  LOW: "Low",
  VERY_LOW: "Very low",
  UNKNOWN: "No survey records",
};
