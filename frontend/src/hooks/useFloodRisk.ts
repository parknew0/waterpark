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
    loading: false,
    error: null,
  });
  const inFlight = useRef<AbortController | null>(null);

  const query = useCallback(async (request: FloodRiskRequest) => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setState((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const response = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
        signal: controller.signal,
      });
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
    } catch (error) {
      // An abort is this hook superseding itself, not a failure to report.
      if (error instanceof DOMException && error.name === "AbortError") return null;
      setState({
        data: null,
        loading: false,
        error: "위험도를 불러오지 못했습니다",
      });
      return null;
    }
  }, []);

  useEffect(() => {
    if (!point) return;
    void query({
      lat: point.lat,
      lon: point.lon,
      nearbyParking: { include: true, radiusM: 1000, limit: 5 },
    });
  }, [point?.lat, point?.lon, query]);

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
