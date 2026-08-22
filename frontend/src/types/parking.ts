export interface Coordinate {
  latitude: number;
  longitude: number;
}

export interface ParkingPlace extends Coordinate {
  id: string;
  name: string;
  address: string;
  cityCounty?: string;
  distanceMeters?: number;
  capacity?: number;
  parkingType?: string;
  placeUrl?: string;
  imageUrl?: string;
  source: "kakao" | "public-data";
}

export type SearchSource = "kakao" | "public-data";
