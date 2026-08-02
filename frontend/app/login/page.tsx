"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Lock, LoaderCircle, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { login } from "@/lib/auth";

/**
 * Single shared-secret login (phase2.md §5.2).
 *
 * The whole admin panel sits behind this one field, so failure messages are
 * specific enough to be actionable ("server unreachable" vs "wrong secret")
 * without ever confirming whether a secret is configured -- that distinction
 * would tell an attacker the deployment is unconfigured.
 */
export default function LoginPage(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!secret.trim() || isSubmitting) return;

    setIsSubmitting(true);
    setError(null);

    const result = await login(secret);

    if (result.ok) {
      // Return the user to wherever they were headed before being bounced here.
      const next = searchParams.get("next");
      router.push(next && next.startsWith("/") ? next : "/");
      router.refresh();
      return;
    }

    setError(
      result.reason === "rate_limited"
        ? "Too many attempts. Wait a minute and try again."
        : result.reason === "network"
          ? "Cannot reach the server. Check that the backend is running."
          : "Incorrect secret.",
    );
    setSecret("");
    setIsSubmitting(false);
  }

  return (
    <div className="flex min-h-[80vh] items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent/10">
            <Lock className="h-6 w-6 text-accent" aria-hidden="true" />
          </div>
          <h1 className="text-2xl font-bold text-textPrimary">Sign in</h1>
          <p className="mt-1 text-sm text-textSecondary">
            kiachahiye.com Product Automation
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label
              htmlFor="secret"
              className="mb-1.5 block text-sm font-medium text-textPrimary"
            >
              Access secret
            </label>
            <Input
              id="secret"
              name="secret"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              aria-invalid={error !== null}
              aria-describedby={error ? "login-error" : undefined}
              disabled={isSubmitting}
            />
          </div>

          {error !== null && (
            <p
              id="login-error"
              role="alert"
              className="flex items-start gap-2 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger"
            >
              <TriangleAlert className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
              <span>{error}</span>
            </p>
          )}

          <Button
            type="submit"
            disabled={isSubmitting || secret.trim().length === 0}
            className="w-full bg-accent py-3 hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? (
              <span className="flex items-center justify-center gap-2">
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                Signing in…
              </span>
            ) : (
              "Sign in"
            )}
          </Button>
        </form>

        <p className="mt-6 text-center text-xs text-textSecondary">
          Your session ends when you close this tab.
        </p>
      </div>
    </div>
  );
}
