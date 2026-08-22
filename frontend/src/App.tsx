import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AppHeader } from "./components/AppHeader";
import { LocationConsentView } from "./components/onboarding/LocationConsentView";
import { OnboardingCarView } from "./components/onboarding/OnboardingCarView";
import { ParkingMap } from "./components/ParkingMap";
import { ParkingSearchPanel } from "./components/ParkingSearchPanel";
import { useParkingSearch } from "./hooks/useParkingSearch";
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
  const [query, setQuery] = useState("");
  const [center, setCenter] = useState<Coordinate>(DEFAULT_CENTER);
  const [selected, setSelected] = useState<ParkingPlace>();
  const [locationPending, setLocationPending] = useState(false);
  const [locationMessage, setLocationMessage] = useState<string | null>(null);
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
    if (nextView === "car") {
      url.searchParams.delete("view");
    } else {
      url.searchParams.set("view", nextView);
    }
    window.history.pushState(null, "", url);
    setView(nextView);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSelected(undefined);
    void search(query, center);
  };

  const handleUseLocation = () => {
    if (!navigator.geolocation) {
      setLocationMessage("이 브라우저는 위치 확인을 지원하지 않습니다. 주소로 검색해 주세요.");
      return;
    }
    setLocationMessage(null);
    setLocationPending(true);
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
        void search("", nextCenter);
      },
      () => {
        setLocationPending(false);
        setLocationMessage("위치 권한을 확인하지 못했습니다. 주소로 검색하거나 브라우저 권한을 허용해 주세요.");
      },
      { enableHighAccuracy: false, timeout: 8_000, maximumAge: 300_000 },
    );
  };

  const handleSelect = (place: ParkingPlace) => {
    setSelected(place);
    setCenter({ latitude: place.latitude, longitude: place.longitude });
  };

  const handleAgreeAndStart = () => {
    navigateToView("map");
    handleUseLocation();
  };

  if (view === "car") {
    return <OnboardingCarView onNext={() => navigateToView("consent")} />;
  }

  if (view === "consent") {
    return <LocationConsentView onAgree={handleAgreeAndStart} />;
  }

  return (
    <>
      <a className="skip-link" href="#main-content">검색 화면으로 건너뛰기</a>
      <main id="main-content" className="app-shell">
        <AppHeader onUseLocation={handleUseLocation} locationPending={locationPending} />
        {locationMessage ? <p className="location-message" role="status" aria-live="polite">{locationMessage}</p> : null}
        <section className="map-stage" aria-label="주차장 지도와 검색">
          <ParkingMap
            appKey={kakaoAppKey}
            center={center}
            places={places}
            selected={selectedPlace}
            onSelect={handleSelect}
          />
          <div className="risk-card">
            <span>현재 프로토타입</span>
            <strong>안전 대피 주차장으로 검증되기 전의 후보 목록입니다.</strong>
          </div>
        </section>
        <ParkingSearchPanel
          query={query}
          onQueryChange={setQuery}
          onSubmit={handleSubmit}
          places={places}
          selectedId={selectedPlace?.id}
          onSelect={handleSelect}
          source={source}
          isLoading={isLoading}
          error={error}
          hasKakaoKey={Boolean(kakaoAppKey)}
        />
      </main>
    </>
  );
}
