import { useEffect, useRef, useState } from "react";
import { createKakaoMap, loadKakaoMaps } from "../lib/kakaoMaps";
import type { Coordinate, ParkingPlace } from "../types/parking";

interface ParkingMapProps {
  appKey?: string;
  center: Coordinate;
  currentPosition?: Coordinate;
  parkedPlace?: ParkingPlace;
  places: ParkingPlace[];
  selected?: ParkingPlace;
  onSelect: (place: ParkingPlace) => void;
}

function CurrentLocationMarker() {
  return (
    <span className="current-map-marker" role="img" aria-label="현재 위치">
      <span className="current-map-marker-direction-frame" aria-hidden="true">
        <span className="current-map-marker-direction-rotator">
          <span className="current-map-marker-direction-canvas">
            <img className="current-map-marker-direction" src="/assets/parking/current-location-direction.svg" alt="" />
          </span>
        </span>
      </span>
      <span className="current-map-marker-dot-frame" aria-hidden="true">
        <img className="current-map-marker-dot" src="/assets/parking/current-location-dot.svg" alt="" />
      </span>
    </span>
  );
}

function ParkedCarMarker() {
  return (
    <span className="parked-car-marker" aria-label="주차된 내 차 위치">
      <img className="parked-car-body" src="/assets/parking/car-body.svg" alt="" />
      <img className="parked-car-wheel parked-car-wheel--back-left" src="/assets/parking/car-wheel-back-left.svg" alt="" />
      <img className="parked-car-wheel parked-car-wheel--front-left" src="/assets/parking/car-wheel-front-left.svg" alt="" />
      <img className="parked-car-wheel parked-car-wheel--front-right" src="/assets/parking/car-wheel-front-right.svg" alt="" />
      <img className="parked-car-wheel parked-car-wheel--back-right" src="/assets/parking/car-wheel-back-right.svg" alt="" />
    </span>
  );
}

function FallbackMap({ places, selected, onSelect, currentPosition, parkedPlace }: Omit<ParkingMapProps, "appKey" | "center">) {
  const visiblePlaces = places.slice(0, 8);
  return (
    <div className="fallback-map" role="region" aria-label="주차장 위치 미리보기">
      <div className="map-grid" aria-hidden="true" />
      {visiblePlaces.map((place, index) => {
        const column = index % 4;
        const row = Math.floor(index / 4);
        return (
          <button
            className="parking-dot-marker fallback-parking-dot"
            style={{ left: `${14 + column * 23}%`, top: `${38 + row * 28}%` }}
            key={place.id}
            type="button"
            aria-label={`${place.name} 선택`}
            aria-pressed={selected?.id === place.id}
            onClick={() => onSelect(place)}
          >
            <img src="/assets/parking/parking-dot.svg" alt="" />
          </button>
        );
      })}
      <div className="map-center-copy">
        {currentPosition ? <CurrentLocationMarker /> : <span className="map-pulse" aria-hidden="true" />}
      </div>
      {parkedPlace ? <span className="fallback-parked-car"><ParkedCarMarker /></span> : null}
    </div>
  );
}

export function ParkingMap({ appKey, center, currentPosition, parkedPlace, places, selected, onSelect }: ParkingMapProps) {
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
          parkedPlace,
          onSelect,
        );
      })
      .catch((caught: unknown) => {
        if (!disposed) {
          setMapError(caught instanceof Error ? caught.message : "지도를 불러오지 못했습니다.");
        }
      });

    return () => {
      disposed = true;
      clearMarkers();
      mapContainer.replaceChildren();
    };
  }, [appKey, center, currentPosition, onSelect, parkedPlace, places, selected]);

  if (!appKey || mapError) {
    return (
      <div className="map-wrap">
        <FallbackMap
          places={places}
          selected={selected}
          onSelect={onSelect}
          currentPosition={currentPosition}
          parkedPlace={parkedPlace}
        />
        {mapError ? <p className="map-error" role="status">{mapError}</p> : null}
      </div>
    );
  }

  return <div className="kakao-map" ref={mapRef} role="region" aria-label="Kakao 지도 주차장 검색 결과" />;
}
