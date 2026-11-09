/** Labelled input with an error slot. Every form in the app uses this. */

import type { InputHTMLAttributes } from "react";

export interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  name: string;
  error?: string;
  hint?: string;
}

export function Field({ label, name, error, hint, className = "", ...rest }: FieldProps) {
  const describedBy = [error ? `${name}-error` : null, hint ? `${name}-hint` : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={name} className="text-small font-medium text-ink">
        {label}
      </label>
      <input
        id={name}
        name={name}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={[
          "h-10 rounded-[var(--radius-ui)] border bg-surface px-3 text-body text-ink",
          "placeholder:text-muted",
          error ? "border-bear" : "border-line",
          className,
        ].join(" ")}
        {...rest}
      />
      {hint && !error && (
        <p id={`${name}-hint`} className="text-small text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${name}-error`} className="text-small text-bear">
          {error}
        </p>
      )}
    </div>
  );
}
