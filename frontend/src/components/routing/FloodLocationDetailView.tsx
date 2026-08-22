import { ParkingMap } from "../ParkingMap";
import type { FloodAwareRoute } from "../../types/routing";
import { getEnglishParkingLabel } from "../../lib/parkingEnglish";

interface FloodLocationDetailViewProps {
  variant: "danger" | "safe";
  route?: FloodAwareRoute;
  onContinue: () => void;
}

function formatDistance(distanceMeters: number) {
  if (distanceMeters < 1_000) return `${Math.round(distanceMeters)}m`;
  return `${(distanceMeters / 1_000).toFixed(1)}km`;
}

export function FloodLocationDetailView({
  variant,
  route,
  onContinue,
}: FloodLocationDetailViewProps) {
  const isDanger = variant === "danger";
  const parkingLabel = route ? getEnglishParkingLabel(route.destination) : undefined;
  const name = isDanger ? "Current Parking Location" : (parkingLabel?.name ?? "Finding parking…");
  const address = isDanger ? "POSTECH, Nam-gu, Pohang-si, Gyeongsangbuk-do" : (parkingLabel?.address ?? "Calculating a lower-risk candidate");
  const distance = route?.distanceMeters ?? 0;
  const driveMinutes = Math.max(1, Math.ceil(distance / 250));

  return (
    <main className="flood-location-stage">
      <section className={`flood-location-phone flood-location-phone--${variant}`} aria-labelledby="flood-location-name">
        <div className="flood-detail-map" aria-hidden="true">
          {route ? (
            <ParkingMap
              center={route.origin}
              currentPosition={route.origin}
              evacuationRoute={route}
              places={[]}
              onSelect={() => undefined}
            />
          ) : <div className="flood-route-map-loading">Calculating route…</div>}
        </div>

        <header className="flood-detail-header">
          <strong>APP</strong>
          <span><img src="/assets/parking/location.svg" alt="" /> Pohang-si Nam-gu</span>
        </header>

        <div className="flood-detail-rain-chip" aria-label="Demo rainfall 30 millimeters">
          <img src="/assets/parking/rain-cloud.svg" alt="" />
          <span>30mm</span>
        </div>

        <section className="flood-detail-sheet">
          <div className="flood-place-summary">
            <span className={`flood-risk-chip flood-risk-chip--${variant}`}>{isDanger ? "Warning" : "Safe"}</span>
            <h1 id="flood-location-name">{name}</h1>
            <p>{address}</p>
            <div>
              <strong>{driveMinutes} min drive</strong>
              <span>{formatDistance(distance)}</span>
              <span>{isDanger ? "−4m" : "+12m"}</span>
            </div>
          </div>

          <article className={`flood-risk-reason flood-risk-reason--${variant}`}>
            <h2><em>{isDanger ? "High" : "Low"}</em> risk of flooding<br />in the next <em>2 hours</em></h2>
            <span>Here’s Why</span>
            <ul>
              <li>Building is {isDanger ? "lower" : "higher"} than the surrounding</li>
              <li>Rainfall over the past 6 hours</li>
            </ul>
          </article>

          <footer className="flood-detail-footer">
            <button type="button" onClick={onContinue} disabled={!route}>
              {isDanger ? "Find a Lower-Risk Parking Lot" : "Move Your Car Now"}
            </button>
          </footer>
        </section>
      </section>
    </main>
  );
}
