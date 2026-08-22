interface BrandLogoProps {
  className?: string;
}

export function BrandLogo({ className = "" }: BrandLogoProps) {
  return (
    <span className={`brand-logo ${className}`.trim()} aria-label="Waterpark">
      WATERPARK
    </span>
  );
}
