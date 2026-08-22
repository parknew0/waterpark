interface OnboardingProgressProps {
  step: 1 | 2;
}

export function OnboardingProgress({ step }: OnboardingProgressProps) {
  return (
    <div
      className="onboarding-progress"
      role="progressbar"
      aria-label="온보딩 진행률"
      aria-valuemin={1}
      aria-valuemax={2}
      aria-valuenow={step}
      aria-valuetext={`${step}/2 단계`}
    >
      <span className="onboarding-progress-bar onboarding-progress-bar--active" />
      <span className={step === 2 ? "onboarding-progress-bar onboarding-progress-bar--active" : "onboarding-progress-bar"} />
    </div>
  );
}
