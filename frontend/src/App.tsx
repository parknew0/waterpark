import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EmergencyView } from "./components/emergency/EmergencyView";
import { LocationConsentView } from "./components/onboarding/LocationConsentView";
import { OnboardingCarView } from "./components/onboarding/OnboardingCarView";
import { ParkingHomeView } from "./components/parking-home/ParkingHomeView";
import { EvacuationRouteView } from "./components/routing/EvacuationRouteView";
import { FloodLocationDetailView } from "./components/routing/FloodLocationDetailView";
import { SplashView } from "./components/splash/SplashView";
import { useParkingSearch } from "./hooks/useParkingSearch";
import { useDeviceHeading } from "./hooks/useDeviceHeading";
import { useFloodAwareRoute } from "./hooks/useFloodAwareRoute";
import { reverseGeocodeKakao } from "./lib/kakaoMaps";
import { getEnglishParkingLabel } from "./lib/parkingEnglish";
import type { Coordinate, ParkingPlace } from "./types/parking";

const DEFAULT_CENTER: Coordinate = { latitude: 36.576, longitude: 128.505 };
const kakaoAppKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim();

type AppView = "splash" | "car" | "consent" | "map" | "emergency" | "risk-detail" | "safe-detail" | "route";

function getInitialView(): AppView {
  const view = new URLSearchParams(window.location.search).get("view");
  if (view === "car" || view === "consent" || view === "map" || view === "emergency" || view === "risk-detail" || view === "safe-detail" || view === "route") return view;
  return window.history.state?.waterparkSplashSeen ? "car" : "splash";
}

export default function App() {
  const [view, setView] = useState<AppView>(getInitialView);
  const [center, setCenter] = useState<Coordinate>(DEFAULT_CENTER);
  const [currentPosition, setCurrentPosition] = useState<Coordinate>();
  const [selected, setSelected] = useState<ParkingPlace>();
  const [parkedPlace, setParkedPlace] = useState<ParkingPlace>();
  const [showParkingMarkers, setShowParkingMarkers] = useState(false);
  const [isCarLocationOpen, setIsCarLocationOpen] = useState(view === "map");
  const [showEvacuationRoute, setShowEvacuationRoute] = useState(false);
  const [locationPending, setLocationPending] = useState(false);
  const [currentLocationLabel, setCurrentLocationLabel] = useState("현재 위치 확인 중…");
  const hasRequestedLocation = useRef(false);
  const requestHeadingPermission = useDeviceHeading();
  const { places, source, isLoading, error, search } = useParkingSearch(kakaoAppKey);
  const isFloodDemoView = view === "emergency" || view === "risk-detail" || view === "safe-detail" || view === "route";
  const { route: evacuationRoute, error: routeError } = useFloodAwareRoute(showEvacuationRoute || isFloodDemoView);
  const evacuationParkingLabel = useMemo(
    () => evacuationRoute ? getEnglishParkingLabel(evacuationRoute.destination) : undefined,
    [evacuationRoute],
  );

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
    window.history.pushState({ waterparkSplashSeen: true }, "", url);
    setView(nextView);
  };

  const handleSplashComplete = useCallback(() => {
    window.history.replaceState({ ...window.history.state, waterparkSplashSeen: true }, "", window.location.href);
    setView("car");
  }, []);

  const handleUseLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setCurrentLocationLabel("현재 위치를 확인하지 못했어요");
      return;
    }

    setLocationPending(true);
    setCurrentLocationLabel("현재 위치 확인 중…");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const nextCenter = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        setCurrentPosition(nextCenter);
        setCenter(nextCenter);
        setSelected(undefined);
        setLocationPending(false);
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
    setShowParkingMarkers(false);
    setSelected(undefined);
    navigateToView("map");
    handleUseLocation();
    void requestHeadingPermission();
  };

  const handleOpenSheet = useCallback(() => {
    hasRequestedLocation.current = true;
    setIsCarLocationOpen(true);
    handleUseLocation();
    void requestHeadingPermission();
  }, [handleUseLocation, requestHeadingPermission]);

  const handleSearch = useCallback((query: string) => {
    setSelected(undefined);
    void search(query, center);
  }, [center, search]);

  const handleSelect = useCallback((place: ParkingPlace) => {
    setSelected(place);
    setCenter({ latitude: place.latitude, longitude: place.longitude });
    setIsCarLocationOpen(true);
  }, []);

  const handleSetCarLocation = useCallback(() => {
    if (selectedPlace) setParkedPlace(selectedPlace);
    setShowParkingMarkers(true);
    setIsCarLocationOpen(false);
    setSelected(undefined);
    if (currentPosition) setCenter(currentPosition);
  }, [currentPosition, selectedPlace]);

  if (view === "splash") return <SplashView onComplete={handleSplashComplete} />;
  if (view === "car") return <OnboardingCarView onNext={() => navigateToView("consent")} />;
  if (view === "consent") return <LocationConsentView onAgree={handleOpenParkingHome} />;
  if (view === "emergency") {
    return (
      <EmergencyView
        onBack={() => navigateToView("map")}
        parkingName={evacuationParkingLabel?.name}
        parkingAddress={evacuationParkingLabel?.address}
        distanceMeters={evacuationRoute?.distanceMeters}
        onMoveNow={() => {
          setShowEvacuationRoute(true);
          setIsCarLocationOpen(false);
          setCenter({ latitude: 36.014, longitude: 129.325 });
          navigateToView("risk-detail");
        }}
      />
    );
  }
  if (view === "risk-detail") {
    return (
      <FloodLocationDetailView
        appKey={kakaoAppKey}
        variant="danger"
        route={evacuationRoute}
        onContinue={() => navigateToView("safe-detail")}
      />
    );
  }
  if (view === "safe-detail") {
    return (
      <FloodLocationDetailView
        appKey={kakaoAppKey}
        variant="safe"
        route={evacuationRoute}
        onContinue={() => navigateToView("route")}
      />
    );
  }
  if (view === "route") {
    return <EvacuationRouteView appKey={kakaoAppKey} route={evacuationRoute} onBack={() => navigateToView("safe-detail")} />;
  }

  return (
    <ParkingHomeView
      appKey={kakaoAppKey}
      center={center}
      currentPosition={currentPosition}
      currentLocationLabel={currentLocationLabel}
      error={error}
      evacuationRoute={evacuationRoute}
      isCarLocationOpen={isCarLocationOpen}
      isLoading={isLoading || locationPending}
      parkedPlace={parkedPlace}
      showParkingMarkers={showParkingMarkers}
      onClearSelection={() => setSelected(undefined)}
      onCloseSheet={() => setIsCarLocationOpen(false)}
      onOpenSheet={handleOpenSheet}
      onSearch={handleSearch}
      onSelect={handleSelect}
      onSetCarLocation={handleSetCarLocation}
      places={places}
      selected={selectedPlace}
      source={source}
      routeError={routeError}
    />
  );
}
