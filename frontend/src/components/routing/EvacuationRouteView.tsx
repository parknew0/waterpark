import { ParkingMap } from "../ParkingMap";
import type { FloodAwareRoute } from "../../types/routing";

interface EvacuationRouteViewProps {
  route?: FloodAwareRoute;
  onBack: () => void;
}

function formatDistance(distanceMeters: number) {
  if (distanceMeters < 1_000) return `${Math.round(distanceMeters)}m`;
  return `${(distanceMeters / 1_000).toFixed(1)}km`;
}

export function EvacuationRouteView({ route, onBack }: EvacuationRouteViewProps) {
  const distance = route?.distanceMeters ?? 0;
  const driveMinutes = Math.max(1, Math.ceil(distance / 250));

  return (
    <main className="evacuation-directions-stage">
      <section className="evacuation-directions-phone" aria-label="Lower-risk driving directions">
        <div className="evacuation-directions-map">
          {route ? (
            <ParkingMap
              center={route.origin}
              currentPosition={route.origin}
              evacuationRoute={route}
              places={[]}
              onSelect={() => undefined}
            />
          ) : <div className="flood-route-map-loading">Calculating lower-risk route…</div>}
        </div>

        <button className="evacuation-directions-back" type="button" onClick={onBack} aria-label="Back">
          <img src="/assets/parking/back-arrow.svg" alt="" />
        </button>

        <div className="evacuation-waypoints" aria-label="Route endpoints">
          <article>
            <i className="evacuation-waypoint evacuation-waypoint--origin" />
            <span>Current Location</span>
            <strong>POSTECH Current Parking</strong>
          </article>
          <article>
            <i className="evacuation-waypoint evacuation-waypoint--destination" />
            <span>Destination</span>
            <strong>{route?.destination.name ?? "Finding a lower-risk parking lot…"}</strong>
          </article>
        </div>

        <div className="evacuation-safe-time">
          <span>Safe time</span>
          <strong>30 min</strong>
        </div>

        <div className="evacuation-route-metrics">
          <span>Drive<strong>{driveMinutes} min</strong></span>
          <span>Distance<strong>{formatDistance(distance)}</strong></span>
        </div>

        <p className="evacuation-route-label">LOWER-RISK ROUTE · PROTOTYPE</p>
      </section>
    </main>
  );
}
