import type { ParkingPlace } from "../types/parking";
import { getEnglishParkingLabel } from "../lib/parkingEnglish";

interface ParkingCardProps {
  place: ParkingPlace;
  selected: boolean;
  onSelect: (place: ParkingPlace) => void;
}

const numberFormatter = new Intl.NumberFormat("en-US");

function formatDistance(distance?: number) {
  if (distance == null) return "Distance unavailable";
  if (distance < 1_000) return `${numberFormatter.format(distance)}m`;
  return `${(distance / 1_000).toFixed(1)}km`;
}

export function ParkingCard({ place, selected, onSelect }: ParkingCardProps) {
  const label = getEnglishParkingLabel(place);
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
          <strong>{label.name}</strong>
          <span className="parking-address">{label.address}</span>
          <span className="parking-meta">
            {place.parkingType ? `${place.parkingType} · ` : ""}
            {place.capacity != null ? `${numberFormatter.format(place.capacity)} spaces · ` : ""}
            {formatDistance(place.distanceMeters)}
          </span>
        </span>
      </button>
    </li>
  );
}
