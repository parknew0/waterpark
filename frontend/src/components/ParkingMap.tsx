import { useEffect, useRef, useState } from "react";
import { createKakaoMap, loadKakaoMaps } from "../lib/kakaoMaps";
import { getEnglishParkingLabel } from "../lib/parkingEnglish";
import type { Coordinate, ParkingPlace } from "../types/parking";
import type { FloodAwareRoute, Position } from "../types/routing";

interface ParkingMapProps {
  appKey?: string;
  center: Coordinate;
  currentPosition?: Coordinate;
  evacuationRoute?: FloodAwareRoute;
  parkedPlace?: ParkingPlace;
  places: ParkingPlace[];
  selected?: ParkingPlace;
  showCurrentDirection?: boolean;
  onSelect: (place: ParkingPlace) => void;
}

function CurrentLocationMarker({ showDirection = true }: { showDirection?: boolean }) {
  return (
    <span className={`current-map-marker${showDirection ? "" : " current-map-marker--dot-only"}`} role="img" aria-label="Current location">
      {showDirection ? (
        <span className="current-map-marker-direction-frame" aria-hidden="true">
          <span className="current-map-marker-direction-rotator">
            <span className="current-map-marker-direction-canvas">
              <img className="current-map-marker-direction" src="/assets/parking/current-location-direction.svg" alt="" />
            </span>
          </span>
        </span>
      ) : null}
      <span className="current-map-marker-dot-frame" aria-hidden="true">
        <img className="current-map-marker-dot" src="/assets/parking/current-location-dot.svg" alt="" />
      </span>
    </span>
  );
}

function ParkedCarMarker() {
  return (
    <span className="parked-car-marker" aria-label="Parked car location">
      <img className="parked-car-body" src="/assets/parking/car-body.svg" alt="" />
      <img className="parked-car-wheel parked-car-wheel--back-left" src="/assets/parking/car-wheel-back-left.svg" alt="" />
      <img className="parked-car-wheel parked-car-wheel--front-left" src="/assets/parking/car-wheel-front-left.svg" alt="" />
      <img className="parked-car-wheel parked-car-wheel--front-right" src="/assets/parking/car-wheel-front-right.svg" alt="" />
      <img className="parked-car-wheel parked-car-wheel--back-right" src="/assets/parking/car-wheel-back-right.svg" alt="" />
    </span>
  );
}

function RoutePreview({ route }: { route: FloodAwareRoute }) {
  const coordinates = [route.baselinePath, route.lowerRiskPath, ...route.riskZones.flatMap((zone) => zone.polygons)].flat();
  const longitudes = coordinates.map(([longitude]) => longitude);
  const latitudes = coordinates.map(([, latitude]) => latitude);
  const minLon = Math.min(...longitudes);
  const maxLon = Math.max(...longitudes);
  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const project = ([longitude, latitude]: Position) => {
    const x = 5 + ((longitude - minLon) / Math.max(maxLon - minLon, 0.000001)) * 90;
    const y = 95 - ((latitude - minLat) / Math.max(maxLat - minLat, 0.000001)) * 90;
    return `${x},${y}`;
  };
  return (
    <svg className="fallback-route-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {route.riskZones.flatMap((zone) => zone.polygons.map((polygon, index) => (
        <polygon className={`route-risk-zone route-risk-zone--${zone.level.toLowerCase()}`} points={polygon.map(project).join(" ")} key={`${zone.level}-${index}`} />
      )))}
      <polyline className="route-line route-line--baseline" points={route.baselinePath.map(project).join(" ")} />
      <polyline className="route-line route-line--lower-risk" points={route.lowerRiskPath.map(project).join(" ")} />
      <circle className="route-origin" cx={project([route.origin.longitude, route.origin.latitude]).split(",")[0]} cy={project([route.origin.longitude, route.origin.latitude]).split(",")[1]} r="2.2" />
      <circle className="route-destination" cx={project([route.destination.longitude, route.destination.latitude]).split(",")[0]} cy={project([route.destination.longitude, route.destination.latitude]).split(",")[1]} r="2.2" />
    </svg>
  );
}

function FallbackMap({ places, selected, onSelect, currentPosition, parkedPlace, evacuationRoute, showCurrentDirection }: Omit<ParkingMapProps, "appKey" | "center">) {
  const visiblePlaces = places.slice(0, 8);
  return (
    <div className="fallback-map" role="region" aria-label="Parking location preview">
      <div className="map-grid" aria-hidden="true" />
      {evacuationRoute ? <RoutePreview route={evacuationRoute} /> : null}
      {visiblePlaces.map((place, index) => {
        const column = index % 4;
        const row = Math.floor(index / 4);
        return (
          <button
            className="parking-dot-marker fallback-parking-dot"
            style={{ left: `${14 + column * 23}%`, top: `${38 + row * 28}%` }}
            key={place.id}
            type="button"
            aria-label={`Select ${getEnglishParkingLabel(place).name}`}
            aria-pressed={selected?.id === place.id}
            onClick={() => onSelect(place)}
          >
            <img src="/assets/parking/parking-dot.svg" alt="" />
          </button>
        );
      })}
      <div className="map-center-copy">
        {!evacuationRoute && (currentPosition ? <CurrentLocationMarker showDirection={showCurrentDirection} /> : <span className="map-pulse" aria-hidden="true" />)}
      </div>
      {parkedPlace ? <span className="fallback-parked-car"><ParkedCarMarker /></span> : null}
    </div>
  );
}

export function ParkingMap({ appKey, center, currentPosition, evacuationRoute, parkedPlace, places, selected, showCurrentDirection = true, onSelect }: ParkingMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    if (!appKey || !mapRef.current) return;
    const mapContainer = mapRef.current;
    mapContainer.replaceChildren();
    let disposed = false;
    let clearMarkers: () => void = () => {};

    loadKakaoMaps(appKey)
      .then((maps) => {
        if (disposed || !mapRef.current) return;
        clearMarkers = createKakaoMap(
          maps,
          mapRef.current,
          selected ?? center,
          places,
          currentPosition,
          evacuationRoute,
          parkedPlace,
          showCurrentDirection,
          onSelect,
        );
      })
      .catch((caught: unknown) => {
        if (!disposed) {
          setMapError(caught instanceof Error ? caught.message : "Unable to load the map.");
        }
      });

    return () => {
      disposed = true;
      clearMarkers();
      mapContainer.replaceChildren();
    };
  }, [appKey, center, currentPosition, evacuationRoute, onSelect, parkedPlace, places, selected, showCurrentDirection]);

  if (!appKey || mapError) {
    return (
      <div className="map-wrap">
        <FallbackMap
          places={places}
          selected={selected}
          onSelect={onSelect}
          currentPosition={currentPosition}
          evacuationRoute={evacuationRoute}
          parkedPlace={parkedPlace}
          showCurrentDirection={showCurrentDirection}
        />
        {mapError ? (
          <p className={`map-error${evacuationRoute ? " map-error--route" : ""}`} role="status">
            {evacuationRoute ? "Kakao map unavailable · showing route preview" : mapError}
          </p>
        ) : null}
      </div>
    );
  }

  return <div className="kakao-map" ref={mapRef} role="region" aria-label="Kakao Map parking search results" />;
}
