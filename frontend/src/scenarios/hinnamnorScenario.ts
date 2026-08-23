import type { Coordinate, ParkingPlace } from "../types/parking";

export interface HistoricalWaterparkScenario {
  id: "hinnamnor";
  locationLabel: string;
  origin: Coordinate;
  rainfallLabel: string;
  rainfallAriaLabel: string;
  safeTimeLabel: string;
  routeDataUrl: string;
  alertDelayMs: number;
  currentParkingName: string;
  currentParkingAddress: string;
  safeParkingIds: string[];
  parkingOptions: ParkingPlace[];
}

export const HINNAMNOR_SCENARIO: HistoricalWaterparkScenario = {
  id: "hinnamnor",
  locationLabel: "Gujeong-gil, Ocheon-eup",
  origin: { latitude: 35.9816, longitude: 129.4103 },
  rainfallLabel: "77mm",
  rainfallAriaLabel: "One-hour rainfall: 77 millimeters",
  safeTimeLabel: "1 hour",
  routeDataUrl: "/data/hinnamnor-waterpark-flow.geojson",
  alertDelayMs: 1_800,
  currentParkingName: "Woobang New World Town 1 Underground Parking",
  currentParkingAddress: "7 Indeok-dong, Nam-gu, Pohang-si, Gyeongsangbuk-do",
  safeParkingIds: ["parking:d14f3c7979a80a1bda68"],
  parkingOptions: [
    {
      id: "hinnamnor:woobang-underground",
      name: "우방신세계타운(1차) 지하주차장",
      address: "경상북도 포항시 남구 인덕동 7",
      latitude: 35.9835575,
      longitude: 129.406536,
      distanceMeters: 481,
      parkingType: "지하",
      source: "public-data",
    },
    {
      id: "parking:d14f3c7979a80a1bda68",
      name: "제철복지회관 임시주차장",
      address: "경상북도 포항시 남구 인덕동 47-4",
      latitude: 35.98538485,
      longitude: 129.4007387,
      distanceMeters: 560,
      parkingType: "노외",
      source: "public-data",
    },
    {
      id: "parking:57bbe18dd621fe062dde",
      name: "청림동 노상1",
      address: "경상북도 포항시 남구 청림동 1113-12",
      latitude: 35.989268,
      longitude: 129.403009,
      distanceMeters: 710,
      parkingType: "노상",
      source: "public-data",
    },
  ],
};

export function getHistoricalScenario() {
  return new URLSearchParams(window.location.search).get("scenario") === "hinnamnor"
    ? HINNAMNOR_SCENARIO
    : undefined;
}
