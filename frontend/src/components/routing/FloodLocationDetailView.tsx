import { ParkingMap } from "../ParkingMap";
import type { FloodAwareRoute } from "../../types/routing";
import { getEnglishParkingLabel } from "../../lib/parkingEnglish";
import { BrandLogo } from "../brand/BrandLogo";
import { RainIcon } from "../icons/RainIcon";
import type { ParkingPlace } from "../../types/parking";

interface FloodLocationDetailViewProps {
  appKey?: string;
  variant: "danger" | "safe";
  route?: FloodAwareRoute;
  onContinue: () => void;
  rainfallLabel?: string;
  rainfallAriaLabel?: string;
  currentParkingName?: string;
  currentParkingAddress?: string;
  comparisonMetric?: string;
  riskReasons?: string[];
  riskWord?: string;
  riskBadge?: "warning" | "safe";
  place?: ParkingPlace;
  ctaLabel?: string;
}

function formatDistance(distanceMeters: number) {
  if (distanceMeters < 1_000) return `${Math.round(distanceMeters)}m`;
  return `${(distanceMeters / 1_000).toFixed(1)}km`;
}

export function FloodLocationDetailView({
  appKey,
  variant,
  route,
  onContinue,
  rainfallLabel = "30mm",
  rainfallAriaLabel = "Demo rainfall 30 millimeters",
  currentParkingName = "Current Parking Location",
  currentParkingAddress = "POSTECH, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  comparisonMetric,
  riskReasons,
  riskWord,
  riskBadge,
  place,
  ctaLabel,
}: FloodLocationDetailViewProps) {
  const isDanger = variant === "danger";
  const parkingLabel = route ? getEnglishParkingLabel(route.destination) : undefined;
  const selectedLabel = place ? getEnglishParkingLabel(place) : undefined;
  const name = selectedLabel?.name ?? (isDanger ? currentParkingName : (parkingLabel?.name ?? "Finding parking…"));
  const address = selectedLabel?.address ?? (isDanger ? currentParkingAddress : (parkingLabel?.address ?? "Calculating a lower-risk candidate"));
  const distance = route?.distanceMeters ?? place?.distanceMeters ?? 0;
  const driveMinutes = route?.estimatedDriveMinutes ?? Math.max(1, Math.ceil(distance / 250));

  return (
    <main className="flood-location-stage">
      <section className={`flood-location-phone flood-location-phone--${variant}`} aria-labelledby="flood-location-name">
        <div className="flood-detail-map">
          {route ? (
            <ParkingMap
              appKey={appKey}
              center={route.origin}
              currentPosition={route.origin}
              evacuationRoute={route}
              places={[]}
              showCurrentDirection={false}
              onSelect={() => undefined}
            />
          ) : <div className="flood-route-map-loading">Calculating route…</div>}
        </div>

        <header className="flood-detail-header">
          <BrandLogo />
          <span className="flood-detail-location"><img src="/assets/parking/location.svg" alt="" /> Pohang-si Nam-gu</span>
        </header>

        <div className="flood-detail-rain-chip" aria-label={rainfallAriaLabel}>
          <RainIcon />
          <span>{rainfallLabel}</span>
        </div>

        <section className="flood-detail-sheet">
          <div className="flood-place-summary">
            {/* `variant` says which place this screen is about; the badge
                says how risky it is. They are usually the same, but the
                current parking is not automatically dangerous. */}
            <span
              className={`flood-risk-chip flood-risk-chip--${
                (riskBadge ?? (isDanger ? "warning" : "safe")) === "warning" ? "danger" : "safe"
              }`}
            >
              {(riskBadge ?? (isDanger ? "warning" : "safe")) === "warning" ? "Warning" : "Safe"}
            </span>
            <h1 id="flood-location-name">{name}</h1>
            <p>{address}</p>
            <div>
              <strong>{driveMinutes} min drive</strong>
              <span>{formatDistance(distance)}</span>
              <span>{comparisonMetric ?? (isDanger ? "−4m" : "+12m")}</span>
            </div>
          </div>

          <article className={`flood-risk-reason flood-risk-reason--${variant}`}>
            <h2><em>{riskWord ?? (isDanger ? "High" : "Low")}</em> risk of flooding<br />in the next <em>1 hour</em></h2>
            <span>Here’s Why</span>
            <ul>
              {(
                riskReasons ?? [
                  `Building is ${isDanger ? "lower" : "higher"} than the surrounding`,
                  "Rainfall over the past 6 hours",
                ]
              ).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </article>

          <footer className="flood-detail-footer">
            <button type="button" onClick={onContinue} disabled={!route}>
              {ctaLabel ?? "Move Your Car Now"}
            </button>
          </footer>
        </section>
      </section>
    </main>
  );
}
