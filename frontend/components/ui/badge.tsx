import * as React from "react";
import { cn } from "@/lib/utils";

const VARIANTS = {
  neutral: "bg-muted text-textSecondary",
  success: "bg-success/10 text-success",
  warning: "bg-accentSoft/15 text-amber-700",
  danger: "bg-danger/10 text-danger",
  accent: "bg-accent/10 text-accent",
} as const;

export type BadgeVariant = keyof typeof VARIANTS;

/**
 * Status pill.
 *
 * Always renders its text, never colour alone -- WCAG requires that colour is
 * not the only means of conveying information, and "red vs green dot" is
 * unreadable to a colour-blind operator scanning a review queue.
 */
export function Badge({
  variant = "neutral",
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  readonly variant?: BadgeVariant;
}): React.JSX.Element {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        VARIANTS[variant],
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

/** Maps a pipeline status to its badge treatment, so every screen agrees. */
export function statusVariant(status: string): BadgeVariant {
  const normalised = status.toLowerCase();
  if (normalised.includes("approved") || normalised.includes("exported")) return "success";
  if (normalised.includes("manual_review") || normalised.includes("failed")) return "danger";
  if (normalised.includes("ready_for_qa")) return "accent";
  if (normalised.includes("processing") || normalised.includes("queued")) return "warning";
  return "neutral";
}

/** Turns `ready_for_qa` into `Ready for QA` for display. */
export function humaniseStatus(status: string): string {
  const spaced = status.replace(/_/g, " ").trim();
  const capitalised = spaced.charAt(0).toUpperCase() + spaced.slice(1);
  return capitalised.replace(/\bqa\b/i, "QA").replace(/\bsku\b/i, "SKU");
}
