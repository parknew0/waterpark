import { useCallback, useEffect, useState } from "react";
import { searchKakaoParking } from "../lib/kakaoMaps";
import { findLocalParking, loadLocalParking } from "../lib/localParking";
import type { Coordinate, ParkingPlace, SearchSource } from "../types/parking";

const DEFAULT_CENTER: Coordinate = { latitude: 36.576, longitude: 128.505 };

export function useParkingSearch(appKey?: string) {
  const [catalog, setCatalog] = useState<ParkingPlace[]>([]);
  const [places, setPlaces] = useState<ParkingPlace[]>([]);
  const [source, setSource] = useState<SearchSource>("public-data");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    loadLocalParking()
      .then((loaded) => {
        if (!active) return;
        setCatalog(loaded);
        setPlaces(findLocalParking(loaded, "", DEFAULT_CENTER));
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "주차장 데이터를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const search = useCallback(async (query: string, center?: Coordinate) => {
    const normalizedQuery = query.trim();
    setIsLoading(true);
    setError(null);
    try {
      if (appKey && normalizedQuery) {
        const kakaoPlaces = await searchKakaoParking(appKey, normalizedQuery);
        if (kakaoPlaces.length > 0) {
          setPlaces(kakaoPlaces);
          setSource("kakao");
          return;
        }
      }

      const localPlaces = findLocalParking(catalog, normalizedQuery, center ?? DEFAULT_CENTER);
      setPlaces(localPlaces);
      setSource("public-data");
      if (localPlaces.length === 0) {
        setError("일치하는 주차장이 없습니다. 시군명이나 도로명까지 포함해 검색해 주세요.");
      }
    } catch (caught: unknown) {
      const localPlaces = findLocalParking(catalog, normalizedQuery, center ?? DEFAULT_CENTER);
      setPlaces(localPlaces);
      setSource("public-data");
      setError(
        caught instanceof Error
          ? `${caught.message} 공공데이터 검색 결과로 전환했습니다.`
          : "Kakao 검색에 실패해 공공데이터 검색 결과로 전환했습니다.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [appKey, catalog]);

  return { places, source, isLoading, error, search };
}
