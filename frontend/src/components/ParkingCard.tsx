import type { ParkingPlace } from "../types/parking";

interface ParkingCardProps {
  place: ParkingPlace;
  selected: boolean;
  onSelect: (place: ParkingPlace) => void;
}

const numberFormatter = new Intl.NumberFormat("ko-KR");

function formatDistance(distance?: number) {
  if (distance == null) return "거리 정보 없음";
  if (distance < 1_000) return `${numberFormatter.format(distance)}m`;
  return `${(distance / 1_000).toFixed(1)}km`;
}

export function ParkingCard({ place, selected, onSelect }: ParkingCardProps) {
  return (
    <li className="parking-card-item">
      <button
        className="parking-card"
        type="button"
        aria-pressed={selected}
        onClick={() => onSelect(place)}
      >
        <span className="parking-thumbnail" aria-hidden="true">P</span>
        <span className="parking-card-copy">
          <strong>{place.name}</strong>
          <span className="parking-address">{place.address || "주소 정보 없음"}</span>
          <span className="parking-meta">
            {place.parkingType ? `${place.parkingType} · ` : ""}
            {place.capacity != null ? `${numberFormatter.format(place.capacity)}면 · ` : ""}
            {formatDistance(place.distanceMeters)}
          </span>
        </span>
      </button>
    </li>
  );
}
