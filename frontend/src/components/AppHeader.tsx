interface AppHeaderProps {
  onUseLocation: () => void;
  locationPending: boolean;
}

export function AppHeader({ onUseLocation, locationPending }: AppHeaderProps) {
  return (
    <header className="app-header">
      <div>
        <p className="eyebrow" translate="no">Waterpark</p>
        <h1>내 차 위치 설정</h1>
      </div>
      <button className="location-button" type="button" onClick={onUseLocation} disabled={locationPending}>
        <span aria-hidden="true">◎</span>
        <span className="location-button-label">{locationPending ? "위치 확인 중…" : "내 위치 사용"}</span>
      </button>
    </header>
  );
}
