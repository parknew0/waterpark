import { useEffect, useState } from "react";
import { BrandLogo } from "../brand/BrandLogo";

interface SplashViewProps {
  onComplete: () => void;
}

const FADE_OUT_DELAY_MS = 1_600;
const FADE_OUT_DURATION_MS = 1_100;

export function SplashView({ onComplete }: SplashViewProps) {
  const [isExiting, setIsExiting] = useState(false);

  useEffect(() => {
    const fadeTimer = window.setTimeout(() => setIsExiting(true), FADE_OUT_DELAY_MS);
    const completeTimer = window.setTimeout(onComplete, FADE_OUT_DELAY_MS + FADE_OUT_DURATION_MS);

    return () => {
      window.clearTimeout(fadeTimer);
      window.clearTimeout(completeTimer);
    };
  }, [onComplete]);

  return (
    <main className={`splash-stage${isExiting ? " splash-stage--exiting" : ""}`} aria-label="Waterpark 시작 화면">
      <section className="splash-phone">
        <img className="splash-background" src="/assets/splash/control-panel.png" alt="" />
        <img className="splash-button" src="/assets/splash/waterpark-button.png" alt="" />
        <BrandLogo className="splash-logo" variant="splash" />
      </section>
    </main>
  );
}
