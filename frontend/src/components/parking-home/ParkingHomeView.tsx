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
}

const thumbnails = [
  "/assets/parking/nearby-1.png",
  "/assets/parking/nearby-2.png",
  "/assets/parking/nearby-3.png",
];

const numberFormatter = new Intl.NumberFormat("ko-KR");

function formatDistance(distance?: number) {
  if (distance == null) return "거리 계산 중";
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
      <section className="parking-home-phone" aria-label="내 차 위치와 가까운 주차장">
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
            <strong>{evacuationRoute.destination.name}</strong>
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
          <article className="parked-car-card" aria-label="저장된 내 차 위치">
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
                aria-label={selected ? "가까운 주차장 목록으로 돌아가기" : "지도 화면으로 돌아가기"}
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
                onSetCarLocation={onSetCarLocation}
                riskWord={riskWord}
                riskReasons={riskReasons}
              />
            ) : (
              <>
                <form className="car-location-search" role="search" onSubmit={handleSubmit}>
                  <label className="visually-hidden" htmlFor="car-location-query">주차장 검색</label>
                  <input
                    id="car-location-query"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      event.preventDefault();
                      onSearch(query);
                    }}
                    placeholder="주차장 검색"
                    autoComplete="off"
                  />
                </form>

                <div className="nearby-heading">
                  <span>가까운 순</span>
                </div>

                {isLoading ? <p className="sheet-state" role="status">현재 위치 주변 주차장을 찾고 있어요…</p> : null}
                {error ? <p className="sheet-state sheet-state--error" role="status">{error}</p> : null}
                {!isLoading && nearbyPlaces.length === 0 ? <p className="sheet-state">가까운 주차장을 찾지 못했어요.</p> : null}

                <ul className="nearby-parking-list">
                  {nearbyPlaces.map((place, index) => (
                    <li key={place.id}>
                      <button type="button" className="nearby-parking-card" onClick={() => onSelect(place)}>
                        <ParkingMedia
                          appKey={appKey}
                          className="nearby-parking-image"
                          fallbackSrc={thumbnails[index]}
                          mode="thumbnail"
                          place={place}
                        />
                        <span className="nearby-parking-copy">
                          <span className="nearby-parking-address">{place.address || "주소 정보 없음"}</span>
                          <strong>{place.name}</strong>
                          <span className="nearby-parking-distance">{formatDistance(place.distanceMeters)}</span>
                        </span>
                      </button>
                    </li>
                  ))}
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
  onSetCarLocation,
  riskWord,
  riskReasons,
}: {
  appKey?: string;
  place: ParkingPlace;
  onSetCarLocation: () => void;
  riskWord?: string;
  riskReasons?: [string, string];
}) {
  return (
    <div className="parking-detail">
      <ParkingMedia
        appKey={appKey}
        className="parking-detail-image"
        fallbackSrc="/assets/parking/parking-detail.png"
        place={place}
      />
      <div className="parking-detail-copy">
        <span className="prototype-warning">Warning</span>
        <h2>{place.name}</h2>
        <p>{place.address || "주소 정보 없음"}</p>
        <span className="parking-detail-distance">{formatDistance(place.distanceMeters)}</span>
      </div>
      <div className="parking-risk-preview">
        <h3><span>{riskWord ?? "High"} risk of flooding</span><br />in the next 1 hour</h3>
        <p>Here’s Why</p>
        <ul>
          <li>{riskReasons?.[0] ?? "Building is lower than the surrounding"}</li>
          <li>{riskReasons?.[1] ?? "Rainfall over the past 6 hours"}</li>
        </ul>
      </div>
      <footer className="parking-detail-footer">
        <button type="button" onClick={onSetCarLocation}>Set My Car’s Location</button>
      </footer>
    </div>
  );
}
