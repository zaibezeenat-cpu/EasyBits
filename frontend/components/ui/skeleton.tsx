import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Loading placeholder.
 *
 * `motion-reduce:animate-none` honours prefers-reduced-motion: a pulsing block
 * is exactly the kind of animation that triggers discomfort for motion-
 * sensitive users, and it conveys nothing they lose by having it stilled.
 */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted motion-reduce:animate-none", className)}
      {...props}
    />
  );
}

/** Skeleton shaped like a table, so loading does not collapse the layout. */
export function TableSkeleton({
  rows = 5,
  columns = 4,
}: {
  readonly rows?: number;
  readonly columns?: number;
}): React.JSX.Element {
  return (
    <div className="space-y-2" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-3">
          {Array.from({ length: columns }).map((__, columnIndex) => (
            <Skeleton
              key={columnIndex}
              className={cn("h-10 flex-1", columnIndex === 0 && "max-w-[40%]")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
