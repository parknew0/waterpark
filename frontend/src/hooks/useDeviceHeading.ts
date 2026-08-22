import { useCallback, useEffect, useRef } from "react";

interface CompassOrientationEvent extends DeviceOrientationEvent {
  webkitCompassHeading?: number;
}

interface OrientationEventConstructorWithPermission {
  requestPermission?: (absolute?: boolean) => Promise<PermissionState>;
}

function readCompassHeading(event: CompassOrientationEvent): number | null {
  if (typeof event.webkitCompassHeading === "number") return event.webkitCompassHeading;
  if (event.absolute && typeof event.alpha === "number") return (360 - event.alpha + 360) % 360;
  return null;
}

export function useDeviceHeading() {
  const animationFrame = useRef<number | undefined>(undefined);

  useEffect(() => {
    const updateHeading = (event: Event) => {
      const heading = readCompassHeading(event as CompassOrientationEvent);
      if (heading == null) return;
      if (animationFrame.current != null) cancelAnimationFrame(animationFrame.current);
      animationFrame.current = requestAnimationFrame(() => {
        document.documentElement.style.setProperty("--device-heading", `${heading.toFixed(1)}deg`);
      });
    };

    window.addEventListener("deviceorientationabsolute", updateHeading);
    window.addEventListener("deviceorientation", updateHeading);
    return () => {
      window.removeEventListener("deviceorientationabsolute", updateHeading);
      window.removeEventListener("deviceorientation", updateHeading);
      if (animationFrame.current != null) cancelAnimationFrame(animationFrame.current);
      document.documentElement.style.removeProperty("--device-heading");
    };
  }, []);

  return useCallback(async () => {
    const orientationEvent = window.DeviceOrientationEvent as unknown as OrientationEventConstructorWithPermission | undefined;
    if (!orientationEvent?.requestPermission) return true;
    try {
      return await orientationEvent.requestPermission(true) === "granted";
    } catch {
      return false;
    }
  }, []);
}
