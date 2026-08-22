import { OnboardingProgress } from "./OnboardingProgress";

interface LocationConsentViewProps {
  onAgree: () => void;
}

export function LocationConsentView({ onAgree }: LocationConsentViewProps) {
  return (
    <main className="onboarding-stage">
      <section className="onboarding-phone onboarding-phone--consent" aria-labelledby="location-consent-title">
        <OnboardingProgress step={2} />
        <header className="onboarding-copy onboarding-copy--consent">
          <h1 id="location-consent-title">Agree with term<br />to use our app</h1>
        </header>
        <section className="permission-section" aria-labelledby="required-permission-title">
          <h2 id="required-permission-title">Required</h2>
          <div className="permission-row">
            <span className="permission-icon" aria-hidden="true">
              <img src="/assets/onboarding/location.svg" alt="" width="20" height="23" />
            </span>
            <span className="permission-copy">
              <strong>Location</strong>
              <span>Detect flood risk at your GPS position</span>
            </span>
          </div>
        </section>
        <p className="permission-detail">When WTP detects flood risk, it will automatically route you<br className="permission-detail-break" /> to a safe parking lot based on your saved vehicle info.</p>
        <footer className="onboarding-footer">
          <button className="onboarding-primary-button" type="button" onClick={onAgree}>Agree &amp; Start</button>
        </footer>
      </section>
    </main>
  );
}
