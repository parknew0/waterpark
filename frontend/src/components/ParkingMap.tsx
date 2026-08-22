import { useEffect, useRef, useState } from "react";
import { createKakaoMap, loadKakaoMaps } from "../lib/kakaoMaps";
import type { Coordinate, ParkingPlace } from "../types/parking";

interface ParkingMapProps {
  appKey?: string;
  center: Coordinate;
  currentPosition?: Coordinate;
  places: ParkingPlace[];
  selected?: ParkingPlace;
  onSelect: (place: ParkingPlace) => void;
}

function CurrentLocationMarker() {
  return (
    <span className="current-map-marker" aria-label="현재 위치">
      <img className="current-map-marker-direction" src="/assets/parking/current-location-direction.svg" alt="" />
      <img className="current-map-marker-dot" src="/assets/parking/current-location-dot.svg" alt="" />
    </span>
  );
}

function FallbackMap({ places, selected, onSelect, currentPosition }: Omit<ParkingMapProps, "appKey" | "center">) {
  const visiblePlaces = places.slice(0, 8);
  return (
    <div className="fallback-map" role="region" aria-label="주차장 위치 미리보기">
      <div className="map-grid" aria-hidden="true" />
      {visiblePlaces.map((place, index) => {
        const column = index % 4;
        const row = Math.floor(index / 4);
        return (
          <button
            className="map-marker"
            style={{ left: `${14 + column * 23}%`, top: `${38 + row * 28}%` }}
            key={place.id}
            type="button"
            aria-label={`${place.name} 선택`}
            aria-pressed={selected?.id === place.id}
            onClick={() => onSelect(place)}
          />
        );
      })}
      <div className="map-center-copy">
        {currentPosition ? <CurrentLocationMarker /> : <span className="map-pulse" aria-hidden="true" />}
      </div>
    </div>
  );
}

export function ParkingMap({ appKey, center, currentPosition, places, selected, onSelect }: ParkingMapProps) {
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
        clearMarkers = createKakaoMap(maps, mapRef.current, selected ?? center, places, currentPosition);
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
  }, [appKey, center, currentPosition, places, selected]);

  if (!appKey || mapError) {
    return (
      <div className="map-wrap">
        <FallbackMap places={places} selected={selected} onSelect={onSelect} currentPosition={currentPosition} />
        {mapError ? <p className="map-error" role="status">{mapError}</p> : null}
      </div>
    );
  }

  return <div className="kakao-map" ref={mapRef} role="region" aria-label="Kakao 지도 주차장 검색 결과" />;
}
