import { useEffect } from "react";
import { BrandLogo } from "../brand/BrandLogo";

interface SplashViewProps {
  onComplete: () => void;
}

const SPLASH_DURATION_MS = 1_800;

export function SplashView({ onComplete }: SplashViewProps) {
  useEffect(() => {
    const timer = window.setTimeout(onComplete, SPLASH_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [onComplete]);

  return (
    <main className="splash-stage" aria-label="Waterpark 시작 화면">
      <section className="splash-phone">
        <img className="splash-background" src="/assets/splash/control-panel.png" alt="" />
        <img className="splash-button" src="/assets/splash/waterpark-button.png" alt="" />
        <BrandLogo className="splash-logo" />
      </section>
    </main>
  );
}
