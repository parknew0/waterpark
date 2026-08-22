interface BrandLogoProps {
  className?: string;
  variant?: "default" | "splash";
}

export function BrandLogo({ className = "", variant = "default" }: BrandLogoProps) {
  return (
    <span className={`brand-logo ${className}`.trim()} aria-label="Waterpark">
      <img
        src={variant === "splash" ? "/assets/brand/waterpark-logo-gradient.svg" : "/assets/brand/waterpark-logo.svg"}
        alt=""
      />
    </span>
  );
}
