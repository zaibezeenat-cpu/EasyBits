"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

interface SwitchProps {
  readonly checked: boolean;
  readonly onCheckedChange: (checked: boolean) => void;
  readonly disabled?: boolean;
  readonly label: string;
  readonly id?: string;
  readonly className?: string;
}

/**
 * Accessible on/off toggle.
 *
 * Built on a real <button role="switch"> rather than a styled div so it is
 * keyboard-operable and announced correctly by screen readers for free. `label`
 * is required, not optional: an unlabelled toggle is meaningless to anyone not
 * looking at the screen, and these toggles control things like whether a brand
 * is active on the live store.
 */
export function Switch({
  checked,
  onCheckedChange,
  disabled = false,
  label,
  id,
  className,
}: SwitchProps): React.JSX.Element {
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-accent" : "bg-gray-300",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform duration-200",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}
