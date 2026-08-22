import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LocationConsentView } from "./components/onboarding/LocationConsentView";
import { OnboardingCarView } from "./components/onboarding/OnboardingCarView";
import { ParkingHomeView } from "./components/parking-home/ParkingHomeView";
import { useParkingSearch } from "./hooks/useParkingSearch";
import { reverseGeocodeKakao } from "./lib/kakaoMaps";
import type { Coordinate, ParkingPlace } from "./types/parking";

const DEFAULT_CENTER: Coordinate = { latitude: 36.576, longitude: 128.505 };
const kakaoAppKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim();

type AppView = "car" | "consent" | "map";

function getInitialView(): AppView {
  const view = new URLSearchParams(window.location.search).get("view");
  return view === "consent" || view === "map" ? view : "car";
}

export default function App() {
  const [view, setView] = useState<AppView>(getInitialView);
  const [center, setCenter] = useState<Coordinate>(DEFAULT_CENTER);
  const [selected, setSelected] = useState<ParkingPlace>();
  const [isCarLocationOpen, setIsCarLocationOpen] = useState(view === "map");
  const [locationPending, setLocationPending] = useState(false);
  const [locationMessage, setLocationMessage] = useState<string | null>(null);
  const [currentLocationLabel, setCurrentLocationLabel] = useState("현재 위치 확인 중…");
  const hasRequestedLocation = useRef(false);
  const { places, source, isLoading, error, search } = useParkingSearch(kakaoAppKey);

  const selectedPlace = useMemo(
    () => places.find((place) => place.id === selected?.id) ?? selected,
    [places, selected],
  );

  useEffect(() => {
    const handleHistoryChange = () => setView(getInitialView());
    window.addEventListener("popstate", handleHistoryChange);
    return () => window.removeEventListener("popstate", handleHistoryChange);
  }, []);

  const navigateToView = (nextView: AppView) => {
    const url = new URL(window.location.href);
    if (nextView === "car") url.searchParams.delete("view");
    else url.searchParams.set("view", nextView);
    window.history.pushState(null, "", url);
    setView(nextView);
  };

  const handleUseLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationMessage("이 브라우저는 위치 확인을 지원하지 않습니다. 주소로 검색해 주세요.");
      return;
    }

    setLocationMessage(null);
    setLocationPending(true);
    setCurrentLocationLabel("현재 위치 확인 중…");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const nextCenter = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        setCenter(nextCenter);
        setSelected(undefined);
        setLocationPending(false);
        setLocationMessage("현재 위치와 가까운 주차장 순으로 정렬했습니다.");
        setCurrentLocationLabel(`${nextCenter.latitude.toFixed(5)}, ${nextCenter.longitude.toFixed(5)}`);
        void search("", nextCenter);

        if (kakaoAppKey) {
          void reverseGeocodeKakao(kakaoAppKey, nextCenter)
            .then((address) => {
              if (address) setCurrentLocationLabel(address);
            })
            .catch(() => undefined);
        }
      },
      () => {
        setLocationPending(false);
        setCurrentLocationLabel("현재 위치를 확인하지 못했어요");
        setLocationMessage("위치 권한을 확인하지 못했습니다. 주소로 검색하거나 브라우저 권한을 허용해 주세요.");
      },
      { enableHighAccuracy: false, timeout: 8_000, maximumAge: 300_000 },
    );
  }, [search]);

  useEffect(() => {
    if (view !== "map" || hasRequestedLocation.current) return;
    hasRequestedLocation.current = true;
    handleUseLocation();
  }, [handleUseLocation, view]);

  const handleOpenParkingHome = () => {
    hasRequestedLocation.current = true;
    setIsCarLocationOpen(true);
    setSelected(undefined);
    navigateToView("map");
    handleUseLocation();
  };

  if (view === "car") return <OnboardingCarView onNext={() => navigateToView("consent")} />;
  if (view === "consent") return <LocationConsentView onAgree={handleOpenParkingHome} />;

  return (
    <ParkingHomeView
      appKey={kakaoAppKey}
      center={center}
      currentLocationLabel={currentLocationLabel}
      error={error}
      isCarLocationOpen={isCarLocationOpen}
      isLoading={isLoading || locationPending}
      locationMessage={locationMessage}
      onClearSelection={() => setSelected(undefined)}
      onCloseSheet={() => setIsCarLocationOpen(false)}
      onOpenSheet={() => {
        hasRequestedLocation.current = true;
        setIsCarLocationOpen(true);
        handleUseLocation();
      }}
      onSearch={(query) => {
        setSelected(undefined);
        void search(query, center);
      }}
      onSelect={(place) => {
        setSelected(place);
        setCenter({ latitude: place.latitude, longitude: place.longitude });
      }}
      onSetCarLocation={() => {
        setIsCarLocationOpen(false);
        setLocationMessage(selectedPlace ? `${selectedPlace.name}에 내 차 위치를 설정했습니다.` : null);
      }}
      places={places}
      selected={selectedPlace}
      source={source}
    />
  );
}
