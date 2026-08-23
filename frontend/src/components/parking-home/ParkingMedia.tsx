import { useEffect, useRef, useState } from "react";
import { loadKakaoMaps } from "../../lib/kakaoMaps";
import { getEnglishParkingLabel } from "../../lib/parkingEnglish";
import type { ParkingPlace } from "../../types/parking";

interface ParkingMediaProps {
  appKey?: string;
  className?: string;
  mode?: "thumbnail" | "detail";
  place: ParkingPlace;
}

export function ParkingMedia({ appKey, className = "", mode = "detail", place }: ParkingMediaProps) {
  const liveMediaRef = useRef<HTMLDivElement>(null);
  const [hasLiveMedia, setHasLiveMedia] = useState(false);
  const label = getEnglishParkingLabel(place);

  useEffect(() => {
    if (place.imageUrl || !appKey || !liveMediaRef.current) return;
    const container = liveMediaRef.current;
    let disposed = false;
    let detachRoadviewListener: () => void = () => undefined;

    loadKakaoMaps(appKey)
      .then((maps) => {
        if (disposed) return;
        const position = new maps.LatLng(place.latitude, place.longitude);
        const roadview = new maps.Roadview(container, { disableZoomControl: true });
        const client = new maps.RoadviewClient();
        const frameStreetLevel = () => {
          const viewpoint = roadview.getViewpoint();
          roadview.setViewpoint({ ...viewpoint, tilt: 8, zoom: 0 });
          setHasLiveMedia(true);
        };
        maps.event.addListener(roadview, "init", frameStreetLevel);
        detachRoadviewListener = () => maps.event.removeListener(roadview, "init", frameStreetLevel);
        client.getNearestPanoId(position, 120, (panoId) => {
          if (disposed || panoId == null) return;
          roadview.setPanoId(panoId, position);
        });
      })
      .catch(() => undefined);

    return () => {
      disposed = true;
      detachRoadviewListener();
      container.replaceChildren();
    };
  }, [appKey, mode, place.imageUrl, place.latitude, place.longitude]);

  return (
    <div
      className={`parking-media ${className}`}
      role="img"
      aria-label={place.imageUrl ? `${label.name} exterior` : `Street view near ${label.name}`}
    >
      {place.imageUrl ? (
        <img
          className={`parking-media-source${hasLiveMedia ? " parking-media-source--ready" : ""}`}
          src={place.imageUrl}
          alt=""
          onLoad={() => setHasLiveMedia(true)}
        />
      ) : (
        <div
          className={`parking-media-live parking-media-live--${mode}${hasLiveMedia ? " parking-media-live--ready" : ""}`}
          ref={liveMediaRef}
        />
      )}
    </div>
  );
}
