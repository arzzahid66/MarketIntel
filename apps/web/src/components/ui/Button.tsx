/**
 * The only button in the app.
 *
 * `--action` is reserved for links and buttons; directional colour never
 * appears here. One radius, one border weight, no shadow.
 */

import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md";

const VARIANT: Record<Variant, string> = {
  primary: "bg-action text-white border border-action hover:opacity-90",
  secondary: "bg-surface text-ink border border-line hover:bg-bg",
  ghost: "bg-transparent text-muted border border-transparent hover:text-ink",
};

const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-small",
  md: "h-10 px-4 text-body",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={[
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-ui)]",
        "font-medium transition-opacity",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANT[variant],
        SIZE[size],
        className,
      ].join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}
