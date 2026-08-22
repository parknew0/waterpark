import type { Coordinate, ParkingPlace } from "../types/parking";

export interface KakaoPlaceResult {
  id: string;
  place_name: string;
  address_name: string;
  road_address_name: string;
  x: string;
  y: string;
  distance?: string;
  place_url?: string;
}

interface KakaoLatLng {
  getLat(): number;
  getLng(): number;
}

interface KakaoMapInstance {
  setBounds(bounds: KakaoLatLngBounds): void;
  setCenter(position: KakaoLatLng): void;
}

interface KakaoMarkerInstance {
  setMap(map: KakaoMapInstance | null): void;
}

interface KakaoLatLngBounds {
  extend(position: KakaoLatLng): void;
}

interface KakaoMapsApi {
  load(callback: () => void): void;
  LatLng: new (latitude: number, longitude: number) => KakaoLatLng;
  LatLngBounds: new () => KakaoLatLngBounds;
  Map: new (container: HTMLElement, options: { center: KakaoLatLng; level: number }) => KakaoMapInstance;
  Marker: new (options: { map: KakaoMapInstance; position: KakaoLatLng; title?: string }) => KakaoMarkerInstance;
  services: {
    Status: { OK: string; ZERO_RESULT: string; ERROR: string };
    SortBy: { DISTANCE: string };
    Geocoder: new () => {
      addressSearch(
        address: string,
        callback: (result: Array<{ x: string; y: string }>, status: string) => void,
      ): void;
    };
    Places: new () => {
      keywordSearch(
        keyword: string,
        callback: (result: KakaoPlaceResult[], status: string) => void,
        options?: {
          location?: KakaoLatLng;
          radius?: number;
          sort?: string;
          size?: number;
        },
      ): void;
    };
  };
}

declare global {
  interface Window {
    kakao?: { maps: KakaoMapsApi };
  }
}

let kakaoLoader: Promise<KakaoMapsApi> | undefined;

export function loadKakaoMaps(appKey: string): Promise<KakaoMapsApi> {
  if (window.kakao?.maps) {
    return new Promise((resolve) => window.kakao?.maps.load(() => resolve(window.kakao!.maps)));
  }
  if (kakaoLoader) return kakaoLoader;

  kakaoLoader = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = "kakao-map-sdk";
    script.async = true;
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(appKey)}&autoload=false&libraries=services`;
    script.addEventListener("load", () => {
      if (!window.kakao?.maps) {
        reject(new Error("Kakao 지도 SDK가 초기화되지 않았습니다."));
        return;
      }
      window.kakao.maps.load(() => resolve(window.kakao!.maps));
    });
    script.addEventListener("error", () => reject(new Error(
      `Kakao 지도 SDK를 불러오지 못했습니다. Kakao Developers의 JavaScript SDK 도메인에 ${window.location.origin}을 등록하고 JavaScript 키인지 확인해 주세요.`,
    )));
    document.head.append(script);
  });

  return kakaoLoader;
}

function geocodeAddress(maps: KakaoMapsApi, address: string): Promise<Coordinate | null> {
  const geocoder = new maps.services.Geocoder();
  return new Promise((resolve) => {
    geocoder.addressSearch(address, (result, status) => {
      if (status !== maps.services.Status.OK || result.length === 0) {
        resolve(null);
        return;
      }
      resolve({ latitude: Number(result[0].y), longitude: Number(result[0].x) });
    });
  });
}

export async function searchKakaoParking(appKey: string, address: string): Promise<ParkingPlace[]> {
  const maps = await loadKakaoMaps(appKey);
  const geocoded = await geocodeAddress(maps, address);
  const places = new maps.services.Places();

  return new Promise((resolve, reject) => {
    const options = geocoded
      ? {
          location: new maps.LatLng(geocoded.latitude, geocoded.longitude),
          radius: 20_000,
          sort: maps.services.SortBy.DISTANCE,
          size: 15,
        }
      : { size: 15 };

    places.keywordSearch(
      geocoded ? "주차장" : `${address} 주차장`,
      (result, status) => {
        if (status === maps.services.Status.ZERO_RESULT) {
          resolve([]);
          return;
        }
        if (status !== maps.services.Status.OK) {
          reject(new Error("Kakao 장소 검색이 실패했습니다. 잠시 후 다시 시도해 주세요."));
          return;
        }
        resolve(result.map((place) => ({
          id: `kakao:${place.id}`,
          name: place.place_name,
          address: place.road_address_name || place.address_name,
          latitude: Number(place.y),
          longitude: Number(place.x),
          distanceMeters: place.distance ? Number(place.distance) : undefined,
          placeUrl: place.place_url,
          source: "kakao" as const,
        })));
      },
      options,
    );
  });
}

export function createKakaoMap(
  maps: KakaoMapsApi,
  container: HTMLElement,
  center: Coordinate,
  places: ParkingPlace[],
): () => void {
  const map = new maps.Map(container, {
    center: new maps.LatLng(center.latitude, center.longitude),
    level: 7,
  });
  const markers: KakaoMarkerInstance[] = [];

  if (places.length > 0) {
    const bounds = new maps.LatLngBounds();
    places.forEach((place) => {
      const position = new maps.LatLng(place.latitude, place.longitude);
      bounds.extend(position);
      markers.push(new maps.Marker({ map, position, title: place.name }));
    });
    map.setBounds(bounds);
  } else {
    map.setCenter(new maps.LatLng(center.latitude, center.longitude));
  }

  return () => markers.forEach((marker) => marker.setMap(null));
}
