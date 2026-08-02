# Deploy Runbook — copy/paste on your server

You need: a VPS (Ubuntu is fine), a domain, and ~15 minutes. Run these ON THE
SERVER, not your laptop.

## 1. Install Docker (once)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # then log out and back in
```

## 2. Get the code

```bash
git clone <your-repo-url> kiachahiye
cd kiachahiye
```

## 3. Configure

```bash
cp backend/.env.example backend/.env
nano backend/.env
```
Fill in (minimum):
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`, `GROQ_API_KEY`
- `APP_AUTH_SECRET`, `APP_JWT_SIGNING_KEY`  (long random strings)
- `DOMAIN=panel.kiachahiye.com`  (your real subdomain, for HTTPS)
- optional: `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_CX`

## 4. Point DNS

Add an **A record**: `panel.kiachahiye.com` → your server's IP. Wait for it to
resolve (`ping panel.kiachahiye.com` shows the server IP).

## 5. Apply DB migrations (once)

In the Supabase dashboard → SQL Editor, run the base schema + policies, then each
incremental migration **in filename order** (they are timestamp-prefixed):
- `supabase/migrations/20260721000000_complete_schema.sql`
- `supabase/migrations/20260721000001_add_rls_policies.sql`
- `supabase/migrations/20260722000000_add_missing_review_reason_codes.sql`
- `supabase/migrations/20260722000001_add_web_source_type.sql`
- `supabase/migrations/20260724000000_add_brand_display_name.sql`
- `supabase/migrations/20260724000001_perf_and_hardening.sql`
- `supabase/migrations/20260724000002_fix_function_search_path.sql`

Two of these carry a `-- supabase:disable-transaction` header (enum `ADD VALUE`
cannot run inside a transaction) — run each of those files on its own, not
pasted together with others.

## 6. Launch

```bash
docker compose up -d --build
```
First build takes several minutes (Playwright + Chromium). Caddy gets the TLS
cert automatically once DNS resolves.

## 7. Verify

```bash
docker compose ps                       # all three "running"/"healthy"
curl -fsS https://panel.kiachahiye.com/api/health
```
Then open `https://panel.kiachahiye.com` and log in with your `APP_AUTH_SECRET`.

## If something breaks — paste me the output of:

```bash
docker compose logs backend  --tail=50
docker compose logs frontend --tail=50
docker compose logs caddy    --tail=30
```

## Update later

```bash
git pull && docker compose up -d --build
```
