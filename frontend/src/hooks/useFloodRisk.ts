import { useCallback, useEffect, useRef, useState } from "react";
import type {
  FloodRiskRequest,
  FloodRiskResponse,
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
            error: payload?.error ?? "위험도를 불러오지 못했습니다",
          });
          return null;
        }
        setState({ data: payload as FloodRiskResponse, loading: false, error: null });
        return payload as FloodRiskResponse;
      })
      .catch((caught: unknown) => {
        // An abort is this hook superseding itself, not a failure to report.
        if (caught instanceof DOMException && caught.name === "AbortError") return null;
        setState({ data: null, loading: false, error: "위험도를 불러오지 못했습니다" });
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
    void run(
      { lat, lon, nearbyParking: { include: true, radiusM: 1000, limit: 5 } },
      controller.signal,
    );
    return () => controller.abort();
  }, [lat, lon, run]);

  useEffect(() => () => inFlight.current?.abort(), []);

  return { ...state, query };
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
  VERY_HIGH: "매우 높음",
  HIGH: "높음",
  MODERATE: "보통",
  LOW: "낮음",
  VERY_LOW: "매우 낮음",
  UNKNOWN: "조사 기록 없음",
};
