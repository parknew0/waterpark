import { OnboardingProgress } from "./OnboardingProgress";

interface OnboardingCarViewProps {
  onNext: () => void;
}

export function OnboardingCarView({ onNext }: OnboardingCarViewProps) {
  return (
    <main className="onboarding-stage">
      <section className="onboarding-phone onboarding-phone--car" aria-labelledby="onboarding-car-title">
        <OnboardingProgress step={1} />
        <header className="onboarding-copy onboarding-copy--car">
          <h1 id="onboarding-car-title">We save your car<br />from the rain</h1>
          <p>AI + public weather data predict flood risk<br />up to 1 hour in advance.</p>
        </header>
        <img
          className="onboarding-car-image"
          src="/assets/onboarding/blue-car.png"
          alt="Blue compact car"
          width="422"
          height="422"
          fetchPriority="high"
        />
        <footer className="onboarding-footer">
          <button className="onboarding-primary-button" type="button" onClick={onNext}>Next</button>
        </footer>
      </section>
    </main>
  );
}
