import type { CSSProperties } from "react";
import { OnboardingProgress } from "./OnboardingProgress";

interface OnboardingCarViewProps {
  onNext: () => void;
}

const rainImpacts = [
  { x: 4, y: 422, duration: 1.75, delay: -0.4 },
  { x: 38, y: 430, duration: 1.9, delay: -1.35 },
  { x: 76, y: 448, duration: 1.65, delay: -0.75 },
  { x: 112, y: 469, duration: 2.05, delay: -1.8 },
  { x: 150, y: 493, duration: 1.8, delay: -0.2 },
  { x: 187, y: 519, duration: 1.95, delay: -1.1 },
  { x: 225, y: 543, duration: 1.7, delay: -1.5 },
  { x: 260, y: 566, duration: 2.1, delay: -0.55 },
  { x: 294, y: 588, duration: 1.85, delay: -1.7 },
  { x: 326, y: 612, duration: 2, delay: -0.95 },
  { x: 22, y: 426, duration: 1.6, delay: -1.05 },
  { x: 58, y: 439, duration: 2.15, delay: -0.15 },
  { x: 132, y: 481, duration: 1.72, delay: -1.42 },
  { x: 207, y: 532, duration: 1.88, delay: -0.68 },
  { x: 278, y: 579, duration: 1.66, delay: -1.26 },
  { x: 342, y: 625, duration: 2.08, delay: -0.32 },
] as const;

export function OnboardingCarView({ onNext }: OnboardingCarViewProps) {
  return (
    <main className="onboarding-stage">
      <section className="onboarding-phone onboarding-phone--car" aria-labelledby="onboarding-car-title">
        <OnboardingProgress step={1} />
        <header className="onboarding-copy onboarding-copy--car">
          <h1 id="onboarding-car-title">We save your car<br />from the rain</h1>
          <p>AI + public weather data predict flood risk<br />up to 1 hour in advance.</p>
        </header>
        <div className="onboarding-rain" aria-hidden="true">
          {rainImpacts.map(({ x, y, duration, delay }) => (
            <span
              className="rain-impact"
              key={`${x}-${y}`}
              style={{
                "--rain-x": `${x}px`,
                "--impact-y": `${y}px`,
                "--rain-duration": `${duration}s`,
                "--rain-delay": `${delay}s`,
              } as CSSProperties}
            >
              <span className="rain-drop" />
              <span className="rain-splash" />
            </span>
          ))}
        </div>
        <img
          className="onboarding-car-image"
          src="/assets/onboarding/white-suv.png"
          alt="White electric SUV"
          width="1402"
          height="1122"
          fetchPriority="high"
        />
        <footer className="onboarding-footer">
          <button className="onboarding-primary-button" type="button" onClick={onNext}>Next</button>
        </footer>
      </section>
    </main>
  );
}
