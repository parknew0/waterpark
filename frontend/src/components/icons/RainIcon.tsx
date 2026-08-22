interface RainIconProps {
  className?: string;
}

const DROP_POSITIONS = ["rain-icon-drop--left", "rain-icon-drop--middle", "rain-icon-drop--right"];

export function RainIcon({ className = "" }: RainIconProps) {
  return (
    <span className={`rain-icon ${className}`.trim()} aria-hidden="true">
      <img className="rain-icon-cloud" src="/assets/parking/rain-cloud-outline-figma.svg" alt="" />
      {DROP_POSITIONS.map((position) => (
        <img
          className={`rain-icon-drop ${position}`}
          src="/assets/parking/rain-drop-figma.svg"
          alt=""
          key={position}
        />
      ))}
    </span>
  );
}
