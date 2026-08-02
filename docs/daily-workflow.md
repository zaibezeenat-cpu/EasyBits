# Daily Workflow & Deployment Guide

This is the operator's manual for the kiachahiye.com product-listing system.

---

## What the system does

You paste rows from your product sheet. For each product the system searches the
brand's official site and trusted Pakistani retailers, **cross-checks every fact
across at least two independent sources**, writes SEO-optimised copy under the
Boss Title Rule and Rank Math rules, and produces a 49-column WooCommerce CSV.
Anything it cannot verify is held in **Manual Review** instead of being published
with a guess — that safety gate is the whole point.

---

## One-time setup (deployment)

You need a server (any VPS) with Docker installed, and a domain pointing at it.

1. **Clone the repo** onto the server.

2. **Create `backend/.env`** from the example and fill it in:
   ```bash
   cp backend/.env.example backend/.env
   ```
   Required: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GEMINI_API_KEY`,
   `GROQ_API_KEY`, `APP_AUTH_SECRET`, `APP_JWT_SIGNING_KEY`.
   For HTTPS set `DOMAIN=panel.kiachahiye.com` (your real domain).
   Optional: `GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_CX` (broad-search backup).

3. **Apply the database migrations** in the Supabase SQL editor (one time):
   - `supabase/migrations/20260722000000_add_missing_review_reason_codes.sql`
   - `supabase/migrations/20260722000001_add_web_source_type.sql`
   Without these the app still runs (it falls back safely), but the review queue
   cannot label those reasons precisely.

4. **Point your domain's DNS** A-record at the server's IP.

5. **Bring the stack up:**
   ```bash
   docker compose up -d --build
   ```
   Caddy fetches a TLS certificate automatically the first time. Open
   `https://your-domain` and log in with `APP_AUTH_SECRET`.

Check health any time:
```bash
docker compose ps
curl -fsS https://your-domain/api/health
```

---

## The daily routine

1. **Log in** at `https://your-domain/login`.

2. **New Batch** → paste your sheet rows (S.No, Product Name, two prices,
   Warranty, Status). Click **Preview** — check the parsed SKU, brand, category,
   and especially that **Sale price is the LOWER number** on every row.

3. Let the batch run. Products flow into one of two places:
   - **Ready for QA** — a CSV row was produced.
   - **Review Queue** — the system could not verify something. Each item shows
     *why* (e.g. "only one source states capacity", "sources disagree").

4. **Work the Review Queue.** For each item, open it, read the reason, and either
   fix the input (taxonomy, warranty) or accept that it needs manual research.
   Nothing here reached a CSV — it is waiting on you, which is correct.

5. **Export** the approved products' CSV.

6. **Before importing to WooCommerce**, run the quick checks (below).

7. **Import** the CSV in WooCommerce → Products → Import.

---

## Before every import — the 60-second checklist

1. **Sale price < Regular price** on every row (a swapped price publishes a rise
   as a discount).
2. **Brand and Category casing** match the live store exactly — one wrong letter
   creates a duplicate term.
3. Any field the report marked **UNVERIFIED / CONFLICT / UNKNOWN** — verify by
   hand or drop that spec.
4. **Meta description is 151–155 characters.**
5. **Product name has no "AC" / "Fridge"** abbreviation.
6. `Meta: rank_math_seo_score` is **empty** — let Rank Math compute the real
   score; never hardcode 100.

---

## Keeping sources fresh (Settings & Taxonomy)

- **Taxonomy Manager** — add/confirm brands and categories, and each brand's
  official website. A brand with no official site is searched only on retailers.
- **Sources Manager** — add or reorder trusted retailer sites, and switch between
  **Strict** (only configured sources; anything else escalates) and **Priority**
  (allow broad web as a fallback). Strict is the safe default.
- **Live SKU Snapshot** — upload your current WooCommerce SKU export so the
  duplicate-SKU guard can block a collision before it overwrites a live product.

---

## Updating the deployed system

```bash
git pull
docker compose up -d --build
```
CI (GitHub Actions) runs the tests, lint, and build on every push, so a broken
change is caught before you deploy it.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `/api/health` fails | `docker compose logs backend` — usually a missing env var |
| Login always fails | `APP_AUTH_SECRET` mismatch between your input and `.env` |
| No HTTPS certificate | `DOMAIN` not set, or DNS not pointing at the server yet |
| Every product escalates | Too few sources configured — add retailers in Settings, or set the Google search keys |
| API calls 404 from the browser | Caddy `/api` routing — confirm the Caddyfile proxies `/api/*` **without** stripping the prefix |
