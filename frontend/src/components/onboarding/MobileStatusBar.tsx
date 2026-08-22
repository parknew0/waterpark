export function MobileStatusBar() {
  return (
    <div className="mobile-status-bar" aria-hidden="true">
      <span className="mobile-status-time">9:41</span>
      <span className="mobile-dynamic-island" />
      <span className="mobile-status-icons">
        <span className="mobile-signal"><i /><i /><i /><i /></span>
        <span className="mobile-wifi"><i /><i /><i /></span>
        <span className="mobile-battery"><i /></span>
      </span>
    </div>
  );
}
