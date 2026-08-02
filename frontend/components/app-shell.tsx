"use client";

import * as React from "react";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  LayoutDashboard,
  Layers,
  Package,
  Tag,
  Settings,
  FileCode,
  ClipboardList,
  ScrollText,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import { isAuthenticated, logout, redirectToLogin } from "@/lib/auth";

const NAV_ITEMS = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Batches", href: "/batches", icon: Layers },
  { name: "Products", href: "/products", icon: Package },
  { name: "Review Queue", href: "/review-queue", icon: ClipboardList },
  { name: "Templates", href: "/templates", icon: FileCode },
  { name: "Taxonomy", href: "/taxonomy", icon: Tag },
  { name: "Audit Log", href: "/audit-log", icon: ScrollText },
  { name: "Settings", href: "/settings", icon: Settings },
] as const;

/** Routes rendered without the shell, and reachable without a session. */
const PUBLIC_ROUTES = ["/login"] as const;

/**
 * Application shell: sidebar navigation plus the client-side auth guard.
 *
 * The guard runs in an effect rather than during render because sessionStorage
 * does not exist during server rendering -- reading it in the render path would
 * make every page crash on the server.
 */
/**
 * Subscribes to session changes. `storage` fires when another tab signs out,
 * so this tab follows instead of holding a stale session.
 */
function subscribeToSession(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

export function AppShell({ children }: { children: React.ReactNode }): React.JSX.Element {
  const pathname = usePathname();
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);

  const isPublicRoute = PUBLIC_ROUTES.some((route) => pathname === route);

  // useSyncExternalStore rather than useState+useEffect: sessionStorage is
  // external state, and setting state inside an effect triggers cascading
  // renders (flagged by react-hooks/set-state-in-effect). The server snapshot
  // is always false because a session cannot exist during server rendering.
  const hasSession = React.useSyncExternalStore(
    subscribeToSession,
    () => isAuthenticated(),
    () => false,
  );

  // The effect performs only the redirect -- a side effect on an external
  // system (the browser URL) -- and never sets React state.
  useEffect(() => {
    if (!isPublicRoute && !hasSession) {
      redirectToLogin();
    }
  }, [isPublicRoute, hasSession]);

  if (isPublicRoute) {
    return <main className="min-h-screen bg-background">{children}</main>;
  }

  if (!hasSession) {
    return (
      <div
        className="flex min-h-screen items-center justify-center bg-background"
        role="status"
        aria-live="polite"
      >
        <span className="text-sm text-textSecondary">Checking your session…</span>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* Mobile top bar */}
      <div className="flex items-center justify-between border-b border-border bg-secondary px-4 py-3 lg:hidden">
        <span className="font-bold text-primary">kiachahiye.com</span>
        <button
          type="button"
          onClick={() => setIsMobileNavOpen((open) => !open)}
          aria-expanded={isMobileNavOpen}
          aria-controls="mobile-nav"
          aria-label={isMobileNavOpen ? "Close navigation" : "Open navigation"}
          className="cursor-pointer rounded-md p-2 text-secondary-foreground transition-colors hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {isMobileNavOpen ? (
            <X className="h-5 w-5" aria-hidden="true" />
          ) : (
            <Menu className="h-5 w-5" aria-hidden="true" />
          )}
        </button>
      </div>

      <aside
        id="mobile-nav"
        className={`${
          isMobileNavOpen ? "block" : "hidden"
        } w-full flex-shrink-0 flex-col bg-secondary text-secondary-foreground lg:flex lg:w-64`}
      >
        <div className="hidden p-6 lg:block">
          <h1 className="text-xl font-bold text-primary">kiachahiye.com</h1>
          <p className="mt-1 text-xs text-muted-foreground">Product Automation</p>
        </div>

        <nav className="flex-1 space-y-1 px-4 py-2" aria-label="Main">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.name}
                href={item.href}
                // Closed here rather than in an effect on `pathname`: reacting
                // to navigation with setState is another cascading render.
                onClick={() => setIsMobileNavOpen(false)}
                aria-current={isActive ? "page" : undefined}
                className={`flex cursor-pointer items-center gap-3 rounded-md px-3 py-2.5 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                  isActive ? "bg-white/15 font-medium" : "hover:bg-white/10"
                }`}
              >
                <item.icon className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-white/10 p-4">
          <button
            type="button"
            onClick={logout}
            className="flex w-full cursor-pointer items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <LogOut className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <main className="flex-1 bg-muted/30">
        <div className="p-4 sm:p-6 lg:p-8">{children}</div>
      </main>
    </div>
  );
}
