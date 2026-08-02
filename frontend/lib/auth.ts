/**
 * Token storage and session handling for the admin panel.
 *
 * The backend requires `Authorization: Bearer <token>` on every /api/* route.
 * Before this existed the frontend sent no token at all, so every page would
 * have returned 401 at runtime even though the build passed cleanly -- a green
 * build cannot detect a missing header.
 */

const TOKEN_KEY = "kiachahiye_access_token";
const EXPIRY_KEY = "kiachahiye_token_expires_at";

/**
 * Result type instead of throwing, per the project's TypeScript conventions:
 * a wrong password is an expected outcome, not an exceptional one, and the
 * caller must be forced to handle it.
 */
export type LoginResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: "invalid" | "rate_limited" | "network" };

interface LoginResponse {
  readonly access_token: string;
  readonly token_type: string;
  readonly expires_in: number;
}

/**
 * sessionStorage, not localStorage: the token dies with the tab. On a shared
 * or office machine a forgotten localStorage token leaves the whole product
 * database reachable by the next person to open the browser.
 */
function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage;
}

export function getToken(): string | null {
  const store = storage();
  if (!store) return null;

  const token = store.getItem(TOKEN_KEY);
  const expiresAt = store.getItem(EXPIRY_KEY);
  if (!token || !expiresAt) return null;

  // Expire slightly early so a request cannot be sent with a token that dies
  // in flight, which would surface as a confusing mid-action logout.
  if (Date.now() > Number(expiresAt) - 30_000) {
    clearToken();
    return null;
  }
  return token;
}

export function setToken(token: string, expiresInSeconds: number): void {
  const store = storage();
  if (!store) return;
  store.setItem(TOKEN_KEY, token);
  store.setItem(EXPIRY_KEY, String(Date.now() + expiresInSeconds * 1000));
}

export function clearToken(): void {
  const store = storage();
  if (!store) return;
  store.removeItem(TOKEN_KEY);
  store.removeItem(EXPIRY_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function login(secret: string): Promise<LoginResult> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ secret }),
    });

    if (res.status === 429) return { ok: false, reason: "rate_limited" };
    if (!res.ok) return { ok: false, reason: "invalid" };

    const body = (await res.json()) as LoginResponse;
    setToken(body.access_token, body.expires_in);
    return { ok: true };
  } catch {
    // Network failure is distinct from a wrong secret: telling the user
    // "wrong password" when the server is simply unreachable sends them
    // hunting for the wrong problem.
    return { ok: false, reason: "network" };
  }
}

export function logout(): void {
  clearToken();
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
}

/** Sends the user to /login, preserving where they were headed. */
export function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  const current = window.location.pathname + window.location.search;
  const next = current && current !== "/login" ? `?next=${encodeURIComponent(current)}` : "";
  window.location.href = `/login${next}`;
}
