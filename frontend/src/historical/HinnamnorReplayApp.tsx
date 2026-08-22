import { useEffect, useMemo, useRef, useState } from "react";
import { loadKakaoMaps } from "../lib/kakaoMaps";

interface ReplayStep {
  time_kst: string;
  title: string;
  detail: string;
  reconstruction_radius_m: number;
  rainfall_duration_minutes: number;
}

interface ReplayData {
  event: {
    name: string;
    date_kst: string;
    focus: {
      name: string;
      location_label: string;
      latitude: number;
      longitude: number;
      underground_parking_confirmed: boolean;
      underground_floor_count: number;
      surface_elevation_m_min: number;
    };
  };
  rainfall: {
    station: string;
    station_id: string;
    rolling_max_mm: Array<{ duration_minutes: number; rainfall_mm: number }>;
    calendar_day_mm: number;
  };
  river: { name: string; coordinates: Array<[number, number]> };
  timeline: ReplayStep[];
  incident: { summary: string };
  limitations: string[];
}

function circlePath(latitude: number, longitude: number, radiusMeters: number) {
  const latitudeScale = 111_320;
  const longitudeScale = latitudeScale * Math.cos((latitude * Math.PI) / 180);
  return Array.from({ length: 49 }, (_, index) => {
    const angle = (index / 48) * Math.PI * 2;
    return [
      longitude + (Math.cos(angle) * radiusMeters) / longitudeScale,
      latitude + (Math.sin(angle) * radiusMeters) / latitudeScale,
    ] as [number, number];
  });
}

function HistoricalMap({ data, step }: { data: ReplayData; step: ReplayStep }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string>();
  const appKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim();

  useEffect(() => {
    if (!mapRef.current || !appKey) {
      setError("Kakao map key is not configured.");
      return;
    }
    let disposed = false;
    const layers: Array<{ setMap(map: null): void }> = [];

    loadKakaoMaps(appKey).then((maps) => {
      if (disposed || !mapRef.current) return;
      mapRef.current.replaceChildren();
      const focus = data.event.focus;
      const map = new maps.Map(mapRef.current, {
        center: new maps.LatLng(focus.latitude, focus.longitude),
        level: 5,
        draggable: true,
        scrollwheel: true,
      });
      const riverPath = data.river.coordinates.map(
        ([longitude, latitude]) => new maps.LatLng(latitude, longitude),
      );
      layers.push(new maps.Polyline({
        map,
        path: riverPath,
        strokeWeight: 5,
        strokeColor: "#00e8ec",
        strokeOpacity: 0.78,
        zIndex: 3,
      }));

      const influencePath = circlePath(
        focus.latitude,
        focus.longitude,
        step.reconstruction_radius_m,
      ).map(([longitude, latitude]) => new maps.LatLng(latitude, longitude));
      layers.push(new maps.Polygon({
        map,
        path: influencePath,
        strokeWeight: 12,
        strokeColor: "#ff565e",
        strokeOpacity: 0.16,
        fillColor: "#ff303a",
        fillOpacity: 0.18,
        zIndex: 4,
      }));
      layers.push(new maps.Polygon({
        map,
        path: influencePath,
        strokeWeight: 2,
        strokeColor: "#ff7a80",
        strokeOpacity: 0.9,
        fillColor: "#ff303a",
        fillOpacity: 0.08,
        zIndex: 5,
      }));

      const marker = document.createElement("div");
      marker.className = "hinnamnor-site-marker";
      marker.innerHTML = '<span></span><strong>INCIDENT SITE</strong>';
      layers.push(new maps.CustomOverlay({
        map,
        position: new maps.LatLng(focus.latitude, focus.longitude),
        content: marker,
        xAnchor: 0.5,
        yAnchor: 0.5,
        zIndex: 8,
      }));
      setError(undefined);
    }).catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : "Historical map failed to load.");
    });

    return () => {
      disposed = true;
      layers.forEach((layer) => layer.setMap(null));
    };
  }, [appKey, data, step]);

  return (
    <div className="hinnamnor-map-shell">
      <div ref={mapRef} className="hinnamnor-map" aria-label="Historical Hinnamnor incident map" />
      {error && <div className="hinnamnor-map-error" role="status">{error}</div>}
      <span className="hinnamnor-river-label">NAENGCHEON</span>
      <span className="hinnamnor-reconstruction-label">ILLUSTRATIVE IMPACT RADIUS</span>
    </div>
  );
}

function durationLabel(minutes: number) {
  return minutes < 60 ? `${minutes}m` : `${minutes / 60}h`;
}

export function HinnamnorReplayApp() {
  const [data, setData] = useState<ReplayData>();
  const [activeIndex, setActiveIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    fetch("/data/hinnamnor-2022-replay.json")
      .then((response) => {
        if (!response.ok) throw new Error(`Replay data error: ${response.status}`);
        return response.json() as Promise<ReplayData>;
      })
      .then(setData)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Replay data failed to load."));
  }, []);

  useEffect(() => {
    if (!playing || !data) return;
    const timer = window.setInterval(() => {
      setActiveIndex((current) => (current + 1) % data.timeline.length);
    }, 2800);
    return () => window.clearInterval(timer);
  }, [data, playing]);

  const step = data?.timeline[activeIndex];
  const rainfall = useMemo(() => {
    if (!data || !step) return undefined;
    return data.rainfall.rolling_max_mm.find(
      (entry) => entry.duration_minutes === step.rainfall_duration_minutes,
    );
  }, [data, step]);

  if (error) return <main className="hinnamnor-load-state">{error}</main>;
  if (!data || !step || !rainfall) return <main className="hinnamnor-load-state">Loading historical replay…</main>;

  return (
    <main className="hinnamnor-stage">
      <section className="hinnamnor-phone" aria-label="Typhoon Hinnamnor historical replay">
        <HistoricalMap data={data} step={step} />

        <header className="hinnamnor-header">
          <div>
            <span>WATERPARK ARCHIVE · 01</span>
            <h1>HINNAMNOR</h1>
          </div>
          <time dateTime={step.time_kst.replace(" ", "T")}>{step.time_kst.slice(5)} KST</time>
        </header>

        <section className="hinnamnor-event-card" aria-live="polite">
          <span>HISTORICAL RECONSTRUCTION</span>
          <h2>{step.title}</h2>
          <p>{step.detail}</p>
        </section>

        <section className="hinnamnor-data-strip" aria-label="Observed event data">
          <article>
            <span>Rolling rain</span>
            <strong>{rainfall.rainfall_mm}<small>mm / {durationLabel(rainfall.duration_minutes)}</small></strong>
          </article>
          <article>
            <span>Site</span>
            <strong>B{data.event.focus.underground_floor_count}<small>parking confirmed</small></strong>
          </article>
          <article>
            <span>Ground</span>
            <strong>{data.event.focus.surface_elevation_m_min}<small>m DSM</small></strong>
          </article>
        </section>

        <section className="hinnamnor-controls">
          <div className="hinnamnor-timeline">
            {data.timeline.map((item, index) => (
              <button
                key={item.time_kst}
                type="button"
                className={index === activeIndex ? "is-active" : ""}
                onClick={() => { setActiveIndex(index); setPlaying(false); }}
                aria-label={`Show ${item.time_kst} ${item.title}`}
              ><span /></button>
            ))}
          </div>
          <button className="hinnamnor-play" type="button" onClick={() => setPlaying((value) => !value)}>
            {playing ? "Pause replay" : "Play replay"}
          </button>
          <p>{data.event.focus.location_label}</p>
          <small>Red area is a reconstruction cue—not a measured flood boundary.</small>
        </section>
      </section>
    </main>
  );
}
