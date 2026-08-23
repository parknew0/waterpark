import type { CSSProperties } from "react";

interface EmergencyViewProps {
  onBack: () => void;
  onMoveNow: () => void;
  parkingName?: string;
  parkingAddress?: string;
  distanceMeters?: number;
  safeTimeLabel?: string;
  isRouting?: boolean;
  routeError?: string | null;
}

const rainDrops = [
  [3, 1.05, -0.2, 34], [8, 1.28, -0.9, 24], [13, 1.14, -0.5, 40],
  [18, 1.36, -1.1, 29], [24, 1.18, -0.3, 37], [30, 1.42, -1.3, 25],
  [36, 1.1, -0.7, 32], [42, 1.31, -0.1, 44], [48, 1.2, -1, 27],
  [54, 1.39, -0.45, 36], [60, 1.13, -0.8, 23], [66, 1.34, -1.2, 41],
  [72, 1.17, -0.25, 30], [78, 1.44, -0.95, 38], [84, 1.08, -0.6, 26],
  [90, 1.3, -1.4, 43], [96, 1.21, -0.15, 31], [6, 1.38, -1.65, 19],
  [16, 1.24, -1.75, 35], [27, 1.11, -1.55, 22], [39, 1.46, -1.9, 39],
  [51, 1.16, -1.7, 28], [63, 1.33, -2, 33], [75, 1.09, -1.6, 21],
  [87, 1.4, -1.85, 37], [94, 1.19, -2.1, 25],
] as const;

function EmergencyRain() {
  return (
    <div className="emergency-rain" aria-hidden="true">
      {rainDrops.map(([left, duration, delay, length], index) => (
        <span
          className="emergency-rain-drop"
          key={`${left}-${index}`}
          style={{
            "--rain-left": `${left}%`,
            "--rain-speed": `${duration}s`,
            "--rain-wait": `${delay}s`,
            "--rain-length": `${length}px`,
          } as CSSProperties}
        />
      ))}
    </div>
  );
}

function EmergencyCarIcon() {
  return (
    <span className="emergency-car-icon" aria-hidden="true">
      <span className="emergency-car-part emergency-car-body" />
      <span className="emergency-car-part emergency-car-wheel emergency-car-wheel--back-left" />
      <span className="emergency-car-part emergency-car-wheel emergency-car-wheel--front-left" />
      <span className="emergency-car-part emergency-car-wheel emergency-car-wheel--front-right" />
      <span className="emergency-car-part emergency-car-wheel emergency-car-wheel--back-right" />
    </span>
  );
}

export function EmergencyView({
  onBack,
  onMoveNow,
  parkingName = "Finding a lower-risk parking candidate…",
  parkingAddress = "Static flood-risk routing prototype",
  distanceMeters,
  safeTimeLabel = "30min",
  isRouting = false,
  routeError,
}: EmergencyViewProps) {
  return (
    <main className="emergency-stage">
      <section className="emergency-phone" aria-labelledby="emergency-title">
        <EmergencyRain />

        <button className="emergency-back-button" type="button" onClick={onBack} aria-label="Back to map">
          <img src="/assets/parking/back-arrow.svg" alt="" width="16" height="9" />
        </button>

        <div className="emergency-alert" role="img" aria-label="Emergency flood warning">
          <img className="emergency-alert-ring emergency-alert-ring--outer" src="/assets/emergency/alert-ring-outer.svg" alt="" />
          <img className="emergency-alert-ring emergency-alert-ring--middle" src="/assets/emergency/alert-ring-middle.svg" alt="" />
          <img className="emergency-alert-ring emergency-alert-ring--inner" src="/assets/emergency/alert-ring-inner.svg" alt="" />
          <EmergencyCarIcon />
        </div>

        <header className="emergency-copy">
          <h1 id="emergency-title">Move your car<br /><span>right now</span></h1>
        </header>

        <section className="emergency-safe-time" aria-label="Estimated safe time">
          <span>Estimated safe time</span>
          <strong>{safeTimeLabel}</strong>
        </section>

        <article className="emergency-parking-card" aria-label="Assigned safe parking">
          <span>Lower-Risk Parking Candidate</span>
          <strong>{parkingName}</strong>
          <p>{parkingAddress}</p>
          <em>{distanceMeters == null ? "Calculating…" : `${Math.round(distanceMeters)}m by road`}</em>
          {routeError ? <small role="alert">{routeError}</small> : null}
        </article>

        <footer className="emergency-footer">
          <button type="button" onClick={onMoveNow} disabled={isRouting}>
            {isRouting ? "Finding the Safest Route…" : "Move Your Car Now"}
          </button>
        </footer>
      </section>
    </main>
  );
}
