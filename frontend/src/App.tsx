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
import { resolveParkingRiskBranch } from "./lib/parkingRisk";
import { getHistoricalScenario } from "./scenarios/hinnamnorScenario";
import type { Coordinate, ParkingPlace } from "./types/parking";

const DEFAULT_CENTER: Coordinate = { latitude: 36.576, longitude: 128.505 };
const kakaoAppKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim();
const historicalScenario = getHistoricalScenario();

type AppView = "splash" | "car" | "consent" | "map" | "emergency" | "risk-detail" | "safe-detail" | "route";

function getInitialView(): AppView {
  const view = new URLSearchParams(window.location.search).get("view");
  if (view === "car" || view === "consent" || view === "map" || view === "emergency" || view === "risk-detail" || view === "safe-detail" || view === "route") return view;
  return window.history.state?.waterparkSplashSeen ? "car" : "splash";
}

export default function App() {
  const [view, setView] = useState<AppView>(getInitialView);
  const [center, setCenter] = useState<Coordinate>(historicalScenario?.origin ?? DEFAULT_CENTER);
  const [currentPosition, setCurrentPosition] = useState<Coordinate | undefined>(historicalScenario?.origin);
  const [selected, setSelected] = useState<ParkingPlace>();
  const [parkedPlace, setParkedPlace] = useState<ParkingPlace>();
  const [showParkingMarkers, setShowParkingMarkers] = useState(false);
  const [isCarLocationOpen, setIsCarLocationOpen] = useState(view === "map");
  const [showEvacuationRoute, setShowEvacuationRoute] = useState(false);
  const [locationPending, setLocationPending] = useState(false);
  const [currentLocationLabel, setCurrentLocationLabel] = useState(historicalScenario?.locationLabel ?? "현재 위치 확인 중…");
  const [historicalQuery, setHistoricalQuery] = useState("");
  const [isRiskSelectionMode, setIsRiskSelectionMode] = useState(false);
  const [riskAssessmentPending, setRiskAssessmentPending] = useState(false);
  const [assessedPlace, setAssessedPlace] = useState<ParkingPlace>();
  const hasRequestedLocation = useRef(false);
  const historicalAlertTimer = useRef<number | undefined>(undefined);
  const requestHeadingPermission = useDeviceHeading();
  const { places, source, isLoading, error, search } = useParkingSearch(kakaoAppKey);
  const isFloodDemoView = view === "emergency" || view === "risk-detail" || view === "safe-detail" || view === "route";
  const { route: evacuationRoute, error: routeError } = useFloodAwareRoute(
    showEvacuationRoute || isFloodDemoView,
    historicalScenario?.routeDataUrl,
  );
  const visiblePlaces = useMemo(() => {
    if (!historicalScenario) return places;
    const normalizedQuery = historicalQuery.trim().toLocaleLowerCase("ko-KR");
    if (!normalizedQuery) return historicalScenario.parkingOptions;
    return historicalScenario.parkingOptions.filter((place) =>
      `${place.name} ${place.address}`.toLocaleLowerCase("ko-KR").includes(normalizedQuery),
    );
  }, [historicalQuery, places]);
  const evacuationParkingLabel = useMemo(
    () => evacuationRoute ? getEnglishParkingLabel(evacuationRoute.destination) : undefined,
    [evacuationRoute],
  );
  const dangerParkingPlace = useMemo<ParkingPlace>(() => {
    if (parkedPlace) return parkedPlace;
    if (historicalScenario) return historicalScenario.parkingOptions[0];
    const origin = evacuationRoute?.origin ?? currentPosition ?? center;
    return {
      ...origin,
      id: "current-parking-location",
      name: "Current Parking Location",
      address: currentLocationLabel,
      distanceMeters: 0,
      source: "public-data",
    };
  }, [center, currentLocationLabel, currentPosition, evacuationRoute?.origin, parkedPlace]);
  const lowerRiskParkingPlace = useMemo<ParkingPlace | undefined>(() => {
    if (!evacuationRoute) return undefined;
    return {
      ...evacuationRoute.destination,
      distanceMeters: evacuationRoute.distanceMeters,
      source: "public-data",
    };
  }, [evacuationRoute]);
  const riskSelectionPlaces = useMemo(
    () => lowerRiskParkingPlace ? [dangerParkingPlace, lowerRiskParkingPlace] : [dangerParkingPlace],
    [dangerParkingPlace, lowerRiskParkingPlace],
  );

  const selectedPlace = useMemo(
    () => visiblePlaces.find((place) => place.id === selected?.id) ?? selected,
    [selected, visiblePlaces],
  );

  useEffect(() => () => {
    if (historicalAlertTimer.current) window.clearTimeout(historicalAlertTimer.current);
  }, []);

  useEffect(() => {
    const handleHistoryChange = () => setView(getInitialView());
    window.addEventListener("popstate", handleHistoryChange);
    return () => window.removeEventListener("popstate", handleHistoryChange);
  }, []);

  const navigateToView = useCallback((nextView: AppView) => {
    const url = new URL(window.location.href);
    if (nextView === "car") url.searchParams.delete("view");
    else url.searchParams.set("view", nextView);
    window.history.pushState({ waterparkSplashSeen: true }, "", url);
    setView(nextView);
  }, []);

  const handleSplashComplete = useCallback(() => {
    window.history.replaceState({ ...window.history.state, waterparkSplashSeen: true }, "", window.location.href);
    setView("car");
  }, []);

  const handleUseLocation = useCallback(() => {
    if (historicalScenario) {
      setCurrentPosition(historicalScenario.origin);
      setCenter(historicalScenario.origin);
      setSelected(undefined);
      setLocationPending(false);
      setCurrentLocationLabel(historicalScenario.locationLabel);
      return;
    }
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
    if (historicalScenario) {
      setHistoricalQuery(query);
      return;
    }
    void search(query, center);
  }, [center, search]);

  const handleSelect = useCallback(async (place: ParkingPlace) => {
    if (isRiskSelectionMode) {
      if (!lowerRiskParkingPlace) {
        return;
      }
      setRiskAssessmentPending(true);
      setAssessedPlace(place);
      try {
        const branch = await resolveParkingRiskBranch(place, {
          dangerParkingId: dangerParkingPlace.id,
          lowerRiskParkingId: lowerRiskParkingPlace.id,
        });
        navigateToView(branch === "danger" ? "risk-detail" : "safe-detail");
      } finally {
        setRiskAssessmentPending(false);
      }
      return;
    }
    setSelected(place);
    setCenter({ latitude: place.latitude, longitude: place.longitude });
    setIsCarLocationOpen(true);
  }, [dangerParkingPlace.id, isRiskSelectionMode, lowerRiskParkingPlace, navigateToView]);

  const handleSetCarLocation = useCallback(() => {
    if (selectedPlace) setParkedPlace(selectedPlace);
    setShowParkingMarkers(true);
    setIsCarLocationOpen(false);
    setSelected(undefined);
    if (currentPosition) setCenter(currentPosition);
    if (historicalScenario) {
      if (historicalAlertTimer.current) window.clearTimeout(historicalAlertTimer.current);
      historicalAlertTimer.current = window.setTimeout(
        () => navigateToView("emergency"),
        historicalScenario.alertDelayMs,
      );
    }
  }, [currentPosition, navigateToView, selectedPlace]);

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
        safeTimeLabel={historicalScenario?.safeTimeLabel}
        onMoveNow={() => {
          setIsRiskSelectionMode(true);
          setShowParkingMarkers(true);
          setIsCarLocationOpen(false);
          setCenter(evacuationRoute?.origin ?? historicalScenario?.origin ?? { latitude: 36.014, longitude: 129.325 });
          navigateToView("map");
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
        place={assessedPlace ?? dangerParkingPlace}
        rainfallLabel={historicalScenario?.rainfallLabel}
        rainfallAriaLabel={historicalScenario?.rainfallAriaLabel}
        currentParkingName={historicalScenario?.currentParkingName}
        currentParkingAddress={historicalScenario?.currentParkingAddress}
        comparisonMetric={historicalScenario ? "B1" : undefined}
        riskReasons={historicalScenario ? ["Confirmed underground parking use", "Peak 1-hour rainfall reached 77mm"] : undefined}
        ctaLabel="Move Your Car Now"
        onContinue={() => {
          setIsRiskSelectionMode(true);
          setShowParkingMarkers(true);
          setIsCarLocationOpen(false);
          navigateToView("map");
        }}
      />
    );
  }
  if (view === "safe-detail") {
    return (
      <FloodLocationDetailView
        appKey={kakaoAppKey}
        variant="safe"
        route={evacuationRoute}
        place={assessedPlace ?? lowerRiskParkingPlace}
        rainfallLabel={historicalScenario?.rainfallLabel}
        rainfallAriaLabel={historicalScenario?.rainfallAriaLabel}
        comparisonMetric={historicalScenario ? "26 spaces" : undefined}
        riskReasons={historicalScenario ? ["Public-data parking candidate", "Route avoids static high-risk zones"] : undefined}
        ctaLabel="Move Your Car Now"
        onContinue={() => {
          setIsRiskSelectionMode(false);
          setShowEvacuationRoute(true);
          navigateToView("route");
        }}
      />
    );
  }
  if (view === "route") {
    return (
      <EvacuationRouteView
        appKey={kakaoAppKey}
        route={evacuationRoute}
        currentLocationName={historicalScenario?.currentParkingName}
        onBack={() => navigateToView("safe-detail")}
      />
    );
  }

  return (
    <ParkingHomeView
      appKey={kakaoAppKey}
      center={center}
      currentPosition={currentPosition}
      currentLocationLabel={currentLocationLabel}
      error={historicalScenario ? null : error}
      evacuationRoute={isRiskSelectionMode ? undefined : evacuationRoute}
      isCarLocationOpen={isCarLocationOpen}
      isLoading={historicalScenario ? false : isLoading || locationPending}
      parkedPlace={parkedPlace}
      showParkingMarkers={showParkingMarkers}
      onClearSelection={() => setSelected(undefined)}
      onCloseSheet={() => setIsCarLocationOpen(false)}
      onOpenSheet={isRiskSelectionMode ? () => undefined : handleOpenSheet}
      onSearch={handleSearch}
      onSelect={handleSelect}
      onSetCarLocation={handleSetCarLocation}
      places={isRiskSelectionMode ? riskSelectionPlaces : visiblePlaces}
      selected={selectedPlace}
      source={historicalScenario ? "public-data" : source}
      routeError={routeError}
      replayLabel={historicalScenario?.replayLabel}
      rainfallLabel={historicalScenario?.rainfallLabel}
      rainfallAriaLabel={historicalScenario?.rainfallAriaLabel}
      historicalRiskPreview={Boolean(historicalScenario)}
      assessmentMode={isRiskSelectionMode}
      assessmentPending={riskAssessmentPending || !lowerRiskParkingPlace}
    />
  );
}
