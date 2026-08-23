import { useState, type FormEvent } from "react";
import { getEnglishParkingLabel } from "../../lib/parkingEnglish";
import type { Coordinate, ParkingPlace } from "../../types/parking";
import type { FloodAwareRoute } from "../../types/routing";
import { ParkingMap } from "../ParkingMap";
import { BrandLogo } from "../brand/BrandLogo";
import { RainIcon } from "../icons/RainIcon";
import { ParkingMedia } from "./ParkingMedia";

interface ParkingHomeViewProps {
  appKey?: string;
  center: Coordinate;
  currentPosition?: Coordinate;
  currentLocationLabel: string;
  error: string | null;
  evacuationRoute?: FloodAwareRoute;
  isCarLocationOpen: boolean;
  isLoading: boolean;
  parkedPlace?: ParkingPlace;
  showParkingMarkers: boolean;
  onClearSelection: () => void;
  onCloseSheet: () => void;
  onOpenSheet: () => void;
  onSearch: (query: string) => void;
  onSelect: (place: ParkingPlace) => void;
  onSetCarLocation: () => void;
  places: ParkingPlace[];
  selected?: ParkingPlace;
  routeError: string | null;
  rainfallLabel?: string;
  rainfallAriaLabel?: string;
  riskWord?: string;
  riskReasons?: [string, string];
  assessmentMode?: boolean;
  assessmentPending?: boolean;
  parkingRiskState?: "safe" | "warning";
}

const numberFormatter = new Intl.NumberFormat("en-US");

function formatDistance(distance?: number) {
  if (distance == null) return "Calculating distance";
  if (distance < 1_000) return `${numberFormatter.format(Math.round(distance))}m away`;
  return `${(distance / 1_000).toFixed(1)}km away`;
}

export function ParkingHomeView({
  appKey,
  center,
  currentPosition,
  currentLocationLabel,
  error,
  evacuationRoute,
  isCarLocationOpen,
  isLoading,
  parkedPlace,
  showParkingMarkers,
  onClearSelection,
  onCloseSheet,
  onOpenSheet,
  onSearch,
  onSelect,
  onSetCarLocation,
  places,
  selected,
  routeError,
  rainfallLabel = "--mm",
  rainfallAriaLabel = "Rainfall data are unavailable",
  riskWord,
  riskReasons,
  assessmentMode = false,
  assessmentPending = false,
  parkingRiskState = "safe",
}: ParkingHomeViewProps) {
  const [query, setQuery] = useState("");
  const nearbyPlaces = places.slice(0, 3);
  const parkedLabel = parkedPlace ? getEnglishParkingLabel(parkedPlace) : undefined;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSearch(query);
  };

  return (
    <main className="parking-home-stage">
      <section className="parking-home-phone" aria-label="Parking lots near my car">
        <div className="parking-home-map">
          <ParkingMap
            appKey={appKey}
            center={center}
            currentPosition={evacuationRoute?.origin ?? currentPosition}
            evacuationRoute={evacuationRoute}
            parkedPlace={assessmentMode ? undefined : parkedPlace}
            places={showParkingMarkers
              ? (assessmentMode ? places : places.filter((place) => place.id !== parkedPlace?.id)).slice(0, 8)
              : []}
            selected={selected}
            onSelect={onSelect}
          />
        </div>

        {evacuationRoute ? (
          <article className="evacuation-route-card" aria-live="polite">
            <span>LOWER-RISK ROUTE · PROTOTYPE</span>
            <strong>{getEnglishParkingLabel(evacuationRoute.destination).name}</strong>
            <p>{Math.round(evacuationRoute.distanceMeters)}m · Safety not verified</p>
            <small>Route: © OpenStreetMap contributors</small>
          </article>
        ) : null}
        {routeError ? <p className="evacuation-route-error" role="status">{routeError}</p> : null}

        <header className="parking-home-header">
          <BrandLogo />
          <button className="current-location-button" type="button" onClick={onOpenSheet}>
            <span className="current-location-icon" aria-hidden="true">
              <img src="/assets/parking/location.svg" alt="" />
            </span>
            <span>{currentLocationLabel}</span>
          </button>
        </header>

        <div className="parking-weather-chip" aria-label={rainfallAriaLabel}>
          <RainIcon className="weather-icon" />
          <span>{rainfallLabel}</span>
        </div>

        {assessmentMode ? (
          <p className="parking-assessment-prompt" aria-live="polite">
            {assessmentPending ? "Checking flood risk…" : "Select a parking lot to check its flood risk."}
          </p>
        ) : !parkedPlace ? (
          <p className="parking-home-disclaimer">
            Please also refer to emergency alerts and notices from the property management office.
          </p>
        ) : null}
        {parkedPlace && !isCarLocationOpen && !assessmentMode ? (
          <article className="parked-car-card" aria-label="Saved car location">
            <span>My Location</span>
            <strong>{parkedLabel?.name}</strong>
            <p>{parkedLabel?.address}</p>
          </article>
        ) : null}

        {isCarLocationOpen ? <div className="parking-sheet-scrim" aria-hidden="true" /> : null}
        {isCarLocationOpen ? (
          <section className={`car-location-sheet${selected ? " car-location-sheet--detail" : ""}`} aria-labelledby="car-location-title">
            <header className="car-location-sheet-header">
              <button
                className="sheet-back-button"
                type="button"
                aria-label={selected ? "Back to nearby parking lots" : "Back to map"}
                onClick={selected ? onClearSelection : onCloseSheet}
              >
                <img src="/assets/parking/back-arrow.svg" alt="" />
              </button>
              <h1 id="car-location-title">Set My Car’s Location</h1>
            </header>

            {selected ? (
              <ParkingDetail
                appKey={appKey}
                place={selected}
                riskState={parkingRiskState}
                onSetCarLocation={onSetCarLocation}
                riskWord={riskWord}
                riskReasons={riskReasons}
              />
            ) : (
              <>
                <form className="car-location-search" role="search" onSubmit={handleSubmit}>
                  <label className="visually-hidden" htmlFor="car-location-query">Search Parking Lot</label>
                  <input
                    id="car-location-query"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      event.preventDefault();
                      onSearch(query);
                    }}
                    placeholder="Search Parking Lot"
                    autoComplete="off"
                  />
                </form>

                <div className="nearby-heading">
                  <span>Nearest</span>
                </div>

                {isLoading ? <p className="sheet-state" role="status">Finding parking lots near your location…</p> : null}
                {error ? <p className="sheet-state sheet-state--error" role="status">{error}</p> : null}
                {!isLoading && nearbyPlaces.length === 0 ? <p className="sheet-state">No nearby parking lots found.</p> : null}

                <ul className="nearby-parking-list">
                  {nearbyPlaces.map((place) => {
                    const label = getEnglishParkingLabel(place);
                    return (
                      <li key={place.id}>
                        <button type="button" className="nearby-parking-card" onClick={() => onSelect(place)} aria-label={`Select ${label.name}`}>
                          <ParkingMedia
                            appKey={appKey}
                            className="nearby-parking-image"
                            mode="thumbnail"
                            place={place}
                          />
                          <span className="nearby-parking-copy">
                            <span className="nearby-parking-address">{label.address}</span>
                            <strong>{label.name}</strong>
                            <span className="nearby-parking-distance">{formatDistance(place.distanceMeters)}</span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </section>
        ) : null}
      </section>
    </main>
  );
}

function ParkingDetail({
  appKey,
  place,
  riskState,
  onSetCarLocation,
  riskWord,
  riskReasons,
}: {
  appKey?: string;
  place: ParkingPlace;
  riskState: "safe" | "warning";
  onSetCarLocation: () => void;
  riskWord?: string;
  riskReasons?: [string, string];
}) {
  const label = getEnglishParkingLabel(place);
  const isSafe = riskState === "safe";
  return (
    <div className="parking-detail">
      <ParkingMedia
        appKey={appKey}
        className="parking-detail-image"
        place={place}
      />
      <div className="parking-detail-copy">
        <span className={`parking-risk-chip parking-risk-chip--${riskState}`}>
          {isSafe ? "Safe" : "Warning"}
        </span>
        <h2>{label.name}</h2>
        <p>{label.address}</p>
        <span className="parking-detail-distance">{formatDistance(place.distanceMeters)}</span>
      </div>
      <div className={`parking-risk-preview parking-risk-preview--${riskState}`}>
        <h3>
          <span>{riskWord ?? (isSafe ? "Low" : "High")}</span> risk of flooding<br />
          in the next <span>1 hour</span>
        </h3>
        <p>Here’s why</p>
        <ul>
          <li>
            {riskReasons?.[0] ??
              `Building is ${isSafe ? "higher" : "lower"} than the surrounding`}
          </li>
          <li>{riskReasons?.[1] ?? "Rainfall over the past 6 hours"}</li>
        </ul>
      </div>
      <footer className="parking-detail-footer">
        {!isSafe ? (
          <p className="parking-detail-guidance">
            <span className="parking-detail-guidance-icon" aria-hidden="true">
              <img className="parking-detail-guidance-outline" src="/assets/parking/danger-circle-outline.svg" alt="" />
              <img className="parking-detail-guidance-line" src="/assets/parking/danger-circle-line.svg" alt="" />
              <img className="parking-detail-guidance-dot" src="/assets/parking/danger-circle-dot.svg" alt="" />
            </span>
            <span>We’ll immediately guide you to a safer route immediately</span>
          </p>
        ) : null}
        <button type="button" onClick={onSetCarLocation}>Set My Car’s Location</button>
      </footer>
    </div>
  );
}
