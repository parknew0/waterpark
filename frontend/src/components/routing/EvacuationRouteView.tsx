import { ParkingMap } from "../ParkingMap";
import type { FloodAwareRoute } from "../../types/routing";
import { getEnglishParkingLabel } from "../../lib/parkingEnglish";

interface EvacuationRouteViewProps {
  appKey?: string;
  route?: FloodAwareRoute;
  onBack: () => void;
  currentLocationName?: string;
}

function formatDistance(distanceMeters: number) {
  if (distanceMeters < 1_000) return `${Math.round(distanceMeters)}m`;
  return `${(distanceMeters / 1_000).toFixed(1)}km`;
}

export function EvacuationRouteView({ appKey, route, onBack, currentLocationName = "POSTECH Current Parking" }: EvacuationRouteViewProps) {
  const distance = route?.distanceMeters ?? 0;
  const driveMinutes = route?.estimatedDriveMinutes ?? 0;
  const forecastMinutes = route?.forecastHorizonMinutes ?? 0;
  const safeTime = forecastMinutes >= 60 && forecastMinutes % 60 === 0
    ? `${forecastMinutes / 60} hour`
    : `${forecastMinutes} min`;
  const parkingLabel = route ? getEnglishParkingLabel(route.destination) : undefined;

  return (
    <main className="evacuation-directions-stage">
      <section className="evacuation-directions-phone" aria-label="Lower-risk driving directions">
        <div className="evacuation-directions-map">
          {route ? (
            <ParkingMap
              appKey={appKey}
              center={route.origin}
              currentPosition={route.origin}
              evacuationRoute={route}
              places={[]}
              onSelect={() => undefined}
            />
          ) : <div className="flood-route-map-loading">Calculating lower-risk route…</div>}
        </div>

        <button className="evacuation-directions-back" type="button" onClick={onBack} aria-label="Back">
          <span aria-hidden="true"><img src="/assets/parking/back-arrow.svg" alt="" /></span>
        </button>

        <div className="evacuation-waypoints" aria-label="Route endpoints">
          <article>
            <i className="evacuation-waypoint evacuation-waypoint--origin" />
            <span>Current Location</span>
            <strong>{currentLocationName}</strong>
          </article>
          <article>
            <i className="evacuation-waypoint evacuation-waypoint--destination" />
            <span>Destination</span>
            <strong>{parkingLabel?.name ?? "Finding a lower-risk parking lot…"}</strong>
          </article>
        </div>

        <div className="evacuation-safe-time">
          <span>Safe time</span>
          <strong>{safeTime}</strong>
        </div>

        <div className="evacuation-route-metrics">
          <span>Drive<strong>{driveMinutes} min</strong></span>
          <span>Distance<strong>{formatDistance(distance)}</strong></span>
        </div>
      </section>
    </main>
  );
}
