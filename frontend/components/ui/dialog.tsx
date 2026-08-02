"use client";

import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface DialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly title: string;
  readonly description?: string;
  readonly children: React.ReactNode;
  readonly footer?: React.ReactNode;
  readonly className?: string;
}

/**
 * Modal dialog.
 *
 * Implements the three things hand-rolled modals usually miss:
 *   - Escape closes it
 *   - focus moves into the dialog on open and returns to the trigger on close
 *   - Tab is trapped inside while it is open
 *
 * Without focus handling a keyboard user tabs straight out of the dialog into
 * the page behind it, which is both confusing and a real accessibility failure.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  className,
}: DialogProps): React.JSX.Element | null {
  const panelRef = React.useRef<HTMLDivElement>(null);
  const previouslyFocused = React.useRef<HTMLElement | null>(null);

  React.useEffect(() => {
    if (!open) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;

    function focusableElements(): HTMLElement[] {
      const panel = panelRef.current;
      if (!panel) return [];
      return Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));
    }

    // Move focus into the dialog so the next Tab stays inside it.
    const first = focusableElements()[0];
    first?.focus();

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const elements = focusableElements();
      if (elements.length === 0) return;
      const firstEl = elements[0];
      const lastEl = elements[elements.length - 1];
      if (!firstEl || !lastEl) return;

      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault();
        lastEl.focus();
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault();
        firstEl.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    // Stop the page behind scrolling while the dialog is open.
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = originalOverflow;
      previouslyFocused.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
      onMouseDown={(event) => {
        // Close only when the backdrop itself is pressed, not when a drag
        // inside the panel happens to end on the backdrop.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        aria-describedby={description ? "dialog-description" : undefined}
        className={cn(
          "max-h-[90vh] w-full overflow-y-auto rounded-t-xl bg-background shadow-xl sm:max-w-lg sm:rounded-xl",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <h2 id="dialog-title" className="text-lg font-semibold text-textPrimary">
              {title}
            </h2>
            {description !== undefined && (
              <p id="dialog-description" className="mt-1 text-sm text-textSecondary">
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="cursor-pointer rounded-md p-1.5 text-textSecondary transition-colors hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <div className="px-5 py-4">{children}</div>

        {footer !== undefined && (
          <div className="flex flex-col-reverse gap-2 border-t border-border px-5 py-4 sm:flex-row sm:justify-end">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
