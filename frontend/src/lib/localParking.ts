import type { Coordinate, ParkingPlace } from "../types/parking";

const DATA_URL = "/data/gyeongbuk-parking.json";
let parkingRequest: Promise<ParkingPlace[]> | undefined;

export async function loadLocalParking(): Promise<ParkingPlace[]> {
  parkingRequest ??= fetch(DATA_URL).then((response) => {
    if (!response.ok) {
      throw new Error("경북 공영주차장 데이터를 불러오지 못했습니다. 페이지를 새로고침해 주세요.");
    }
    return response.json() as Promise<ParkingPlace[]>;
  });
  return parkingRequest;
}

export function distanceInMeters(from: Coordinate, to: Coordinate): number {
  const earthRadius = 6_371_000;
  const toRadians = (value: number) => (value * Math.PI) / 180;
  const latitudeDelta = toRadians(to.latitude - from.latitude);
  const longitudeDelta = toRadians(to.longitude - from.longitude);
  const fromLatitude = toRadians(from.latitude);
  const toLatitude = toRadians(to.latitude);
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(fromLatitude) * Math.cos(toLatitude) * Math.sin(longitudeDelta / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

export function findLocalParking(
  parking: ParkingPlace[],
  query: string,
  center?: Coordinate,
  limit = 20,
): ParkingPlace[] {
  const terms = query
    .normalize("NFKC")
    .toLocaleLowerCase("ko")
    .split(/\s+/)
    .filter(Boolean);

  const matches = terms.length === 0
    ? parking
    : parking.filter((place) => {
        const searchable = `${place.name} ${place.address} ${place.cityCounty ?? ""}`
          .normalize("NFKC")
          .toLocaleLowerCase("ko");
        return terms.every((term) => searchable.includes(term));
      });

  return matches
    .map((place) => center
      ? { ...place, distanceMeters: Math.round(distanceInMeters(center, place)) }
      : place)
    .sort((a, b) => {
      if (a.distanceMeters != null && b.distanceMeters != null) {
        return a.distanceMeters - b.distanceMeters;
      }
      return a.name.localeCompare(b.name, "ko");
    })
    .slice(0, limit);
}
