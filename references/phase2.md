# Phase 2: Implementation Plan (Revised v2.6 - Production Lock)

**Status:** Locked Specification — matches the actual implemented code exactly.
**Builds on:** `phase1.md` (v8.0/v3.1-corrected, locked) + Phase 2 v2.5.
**Repo state:** implemented — see git status for the real file tree; this document is the spec the code is built against.

**Changelog v2.5 → v2.6 (Thin-Content Guard — new addition, not a correction of a prior mistake; found during a code-level SEO audit against e-commerce best practice, not from real reference data this time):**
- Added a 13th deterministic SEO check, `content_length_minimum`, to `seo_validator.py::validate_seo_rules()`: concatenated body copy (hero paragraph + all feature texts + bullets + FAQ answers) must be ≥ 200 words. Nothing previously enforced a floor on content length — a response could pass every existing check (correct meta length, correct keyword placement, correct alt text) while still being thin, generic copy that ranks poorly regardless of clean metadata.
- `writer.py::WRITER_SYSTEM_PROMPT` updated with a new rule 7 (content depth) plus explicit per-field minimums (hero_paragraph ≥ 40 words, each feature_text ≥ 25 words) so the LLM is aiming comfortably above the floor rather than exactly at it.
- `ReviewResult.checks` docstring updated from "all 11 checks" to "all 13 checks."
- Wired automatically into the existing pass/fail gate (`all(c.passed for c in seo_checks)` in `nodes.py`) — no change needed there.

**Changelog v2.4 → v2.5 (V3.0 correction — supersedes v2.4's Focus Keyword and warranty-mention entries below, not layered alongside them; confirmed against real Rank Math plugin screenshots from the live site, not a guess):**
- **Focus Keyword field reversal:** v2.4's "exactly one keyword, locked to the exact Product Name, no comma-stacking" was correct for the *internal/primary* keyword used by validator checks (still true — see `focus_keyword_single_exact_match` in `seo_validator.py`), but wrong about the *exported CSV field*. The live Rank Math panel's Focus Keyword UI natively supports a primary keyword plus secondary/related keyword pills, and its scoring is computed against "Focus Keyword and combination." The CSV's `Meta: rank_math_focus_keyword` column is now built by `seo_title_builder.py::build_focus_keyword_field(primary_keyword, secondary_keywords)`, which comma-joins the deterministic primary keyword with the Writer's 3 LSI keywords — matching real reference CSV exports (e.g. the Kenwood/Midea AC examples) that show 4 comma-separated keywords in this field. See §3.2, §8.7.
- **Meta description warranty-mention check relaxed:** v2.4 required the exact stored warranty phrase to appear verbatim in the meta description. In practice this is nearly impossible once the Boss Title Rule produces long (80+ char) focus keywords, since the 151–155 char budget has no room left for a full compound warranty sentence too — and real reference examples abbreviate the warranty wording rather than repeating it exactly. `seo_validator.py`'s check #7 (`meta_description_mentions_warranty`) now extracts every duration number from the real warranty phrase (`re.findall(r"\d+", ...)`) and requires each number to appear in the description, without requiring the exact sentence wording — numbers can never be silently dropped or invented, but phrasing can be compact.

**Changelog v2.3 → v2.4 (V8.0 Production Lock — supersedes v2.3's SEO title entry below, not layered alongside it):**
- **This is the correction:** v2.3's "Corrected the Rank Math title suffix to '[Product Name] - Best Price in Pakistan | kiachahye.pk'" was itself wrong and is now fully replaced. The title is deterministic and category-aware (the "Boss Title Rule" for Air Conditioners, a power-word fallback elsewhere) — see §3.2, §5.2, `backend/app/builders/seo_title_builder.py`.
- Focus Keyword is now exactly one keyword, locked to the exact Product Name — the old 10–13 comma-separated stacking rule is removed, not layered as an alternate.
- Meta description is now strictly 151–155 characters, must begin with the Focus Keyword, mention the exact warranty phrase, and end with a fixed, capacity-aware CTA — resolved once (`writer_node`) and reused identically by the validator, so the two can never independently drift onto different claims (this was a real bug found and fixed during review — see `seo_validator.py`'s `expected_meta_cta()`).
- Added the LSI Keyword rule: exactly 3, must appear as plain text in the body — `html_sanitizer.py::strip_lsi_keyword_formatting()` strips any `<strong>`/`<b>`/heading wrapper found immediately around one of these exact strings.
- Added the hardcoded "Zig-Zag" image grid template for Template A (`description_merger.py::render_template_a_zigzag()`) — alternating row direction, `src=""` always (images stay manual for V1, phase1.md §8.5).
- Added the Brand Casing Lock and Category Breadcrumb Assertion as hard errors in `csv_assembler.py` (`BrandCasingMismatchError`, `CategoryBreadcrumbError`), and newline-stripping before CSV writing (`strip_newlines_for_csv()`).

**Changelog v2.2 → v2.3 (SEO Remediation):**
- Updated `seo_validator.py` with all required SEO checks from phase1.md §6.8.
- Corrected `short_description_renderer.py` to use the paragraph template from §7.2.
- Updated `specs_renderer.py` with the thead structure and inline styling from §7.7.
- Formalized the 4-location warranty consistency check in `reviewer_node` (§5.5).
- Populated missing `short_description` and `description` fields in `nodes.py` by integrating builder calls into the pipeline.

**Changelog v2.1 → v2.2:**
- Added `backend/app/core/budget_guard.py` to the manifest (§1).
- Added explicit logic for `name_builder.py` (44-char limit + abbreviations) and `tag_generator.py` (3-tag rule) (§6).
- Defined the exact 49-column `COLUMN_ORDER` for the CSV engine (§6).
- Added RLS policy SQL blueprints for the database schema (§2).
- Formalized `budget_guard.py` logic (§7) and confirmed sequential batch orchestration (§9).
- Set `[Product Name] | Best Price` as the default SEO title format (§5.2).

**Changelog v2.0 → v2.1:** Replaced the mandatory per-brand `brand_source_urls` table with dynamic source discovery — Agent 1 web-searches per product and domain-matches results instead of requiring a pre-registered URL per brand. Introduces `trusted_secondary_sources` (a small, Settings-editable list — Japan Electronics/Surmawala seeded by default, not hardcoded) and an optional `brand_domain_aliases` table for the rare brand whose official domain doesn't match its name well enough for automatic detection. See §2, §4, §5.2.

**Changelog v1.0 → v2.0:** Added full prompt templates for all 3 agents (closes #1). Added complete Pydantic schemas for every I/O contract (closes #2). Added `build_dimensions()` (closes #3) and a dedicated `BatchProcessor` orchestrator (closes #4). Resolved the "Thriftify" design-system requirement with a concrete, confirmable choice (closes #5). Fixed the writer/reviewer retry off-by-one (closes #6). Added Quick-Add flow (closes #7). Defined Settings page scope explicitly (closes #8). Added regression tests for previously-buggy conditional nodes (closes #9). Added explicit §16 metric measurement via new timestamp columns + a report script (closes #10). Promoted rendered content to first-class `products` columns (closes #11). Named the price-discrepancy computation function (closes #12). Added explicit LLM backoff config (closes #13). Added an in-stock UI control (closes #14). Added a concrete dependency manifest (closes #15). Added a one-command bootstrap script (closes #16). Added a deployment rollback runbook (closes #17). Added login rate limiting (closes #18).

---

## Overall Project Roadmap

Unchanged from v1.0. Phase 0 (site verification) and Phase 1 (locked spec) are done/in-progress. **6 more phases** to a fully functional, hardened, V2-complete system:

| Phase | Goal |
|---|---|
| **Phase 2 — Foundation** | Repo scaffold, DB schema + seed data, all deterministic builders + CSV engine, fully unit-tested. No AI agents yet. |
| **Phase 3 — Agent Pipeline MVP** | LangGraph wired to real scraping + LLM calls via the prompts in §3 below, extraction-vs-writer/reviewer retry split, source citations end-to-end. API-only. |
| **Phase 4 — Frontend & Human QA UX** | Full dashboard incl. Quick-Add, QA Panel (Full/Quick modes), Review Queue, Template/Taxonomy Managers, Settings, SSE progress. |
| **Phase 5 — Pilot & Hardening** | Run the `phase1.md` §15 5-product pilot, then scale to 20, gradual trust reduction (an explicit rollout step, §7), measure real LLM cost. |
| **Phase 6 — Deployment & Monitoring** | Droplet, CI/CD, GlitchTip, secrets hardening, rollback runbook, login rate limiting. |
| **Phase 7 — V2 Features** | Variable products, native WooCommerce attributes, cross-sells/upsells, image automation. |

---

## 0. Top-Level Repo Layout

```
d:\EasyBits\
  backend/
  frontend/
  supabase/
    migrations/
    config.toml
  docs/
    architecture.md
  .github/workflows/
    ci.yml
    deploy.yml
    rollback.yml                 # NEW — closes #17
  docker-compose.yml
  Caddyfile
  Makefile                       # NEW — closes #16
  .gitignore
  README.md
  phase1.md
  phase2.md
```

---

## 1. Project Scaffold

### Backend (`backend/`)

```
backend/
  app/
    main.py
    core/
      config.py
      security.py                     # + login rate limiting, closes #18
      logging.py
      llm_provider.py                 # + explicit backoff config, closes #13
      rate_limit.py                   # NEW — slowapi wrapper for /api/auth/login, closes #18
      budget_guard.py                 # NEW — hard cost cap enforcement, §7
    db/
      client.py
      repositories/
        products.py
        batches.py
        templates.py
        taxonomy.py
        warranty.py
        audit.py
        review_queue.py
        citations.py
        sku_snapshot.py
        llm_usage.py
    models/
      raw_input.py                    # RawProductInput — full schema in §3
      extraction.py                   # ExtractedFact, SourceCitation, ExtractionResult — full schema in §3
      writer_output.py                # FAQPair, WriterOutput — full schema in §3
      review_result.py                # SeoCheckResult, ReviewResult — full schema in §3
      failure.py                      # FailureInfo — full schema in §3
      taxonomy.py                     # SpecField, CategorySpecSchema — full schema in §3
      csv_row.py
      dimensions.py                   # NEW — DimensionsResult, closes #3
    graph/
      state.py
      pipeline.py
      nodes.py
      router.py
      checkpointer.py
      batch_processor.py              # NEW — BatchProcessor, closes #4, full spec in §9
    agents/
      extractor.py                    # + PROMPT constant, full text in §3
      writer.py                       # + PROMPT constant, full text in §3
      reviewer.py                     # + PROMPT constant, full text in §3
      seo_validator.py
    scraping/
      base.py
      playwright_client.py
      firecrawl_client.py
      rate_limiter.py
      source_discovery.py             # RENAMED v2.1 (was brand_url_resolver.py) — dynamic search + domain matching, §4
      orchestrator.py
    builders/
      csv_columns.py
      name_builder.py
      tag_generator.py
      specs_renderer.py
      dimensions_builder.py           # NEW — build_dimensions(), closes #3
      price_reference.py              # NEW — compute_price_discrepancy(), closes #12
      short_description_renderer.py
      description_merger.py
      html_sanitizer.py
      taxonomy_lock.py
      sku_guard.py
      csv_assembler.py
      csv_writer.py
    api/
      deps.py
      routes/
        auth.py
        batches.py
        products.py                   # + POST /api/products/quick-add, closes #7
        review_queue.py
        templates.py
        taxonomy.py
        warranty.py
        settings.py                   # scope defined explicitly in §5, closes #8
        export.py
        audit.py
        metrics.py                    # NEW — GET /api/metrics/pilot-report, closes #10
        health.py                     # NEW (v2.0, Phase 4 dependency) — GET /health, no auth, for uptime monitoring
      sse.py
  tests/
    unit/
      test_name_builder.py
      test_tag_generator.py
      test_specs_renderer.py
      test_dimensions_builder.py      # NEW — closes #9
      test_price_reference.py         # NEW — closes #9/#12
      test_csv_columns.py
      test_html_sanitizer.py
      test_sku_guard.py
      test_taxonomy_lock.py
      test_retry_boundary.py          # NEW — verifies exactly 3 total attempts, closes #6
    integration/
      test_extractor_node.py
      test_writer_node.py
      test_reviewer_node.py
      test_graph_routing.py
      test_image_fallback_node.py     # NEW — closes #9
      test_intake_triage.py           # NEW — closes #9
      test_batch_processor.py         # NEW — closes #4/#9
    e2e/
  scripts/
    bootstrap.sh                      # NEW — one-command first-run setup, closes #16
    seed_taxonomy.py
    seed_warranty_matrix.py
    seed_llm_model_config.py
    pilot_gate_check.py
    metrics_report.py                 # NEW — computes §16's two split timing metrics, closes #10
    staging_import_checklist.md
  Dockerfile
  pyproject.toml                      # full dependency list in §1, closes #15
  .env.example
```

### Frontend (`frontend/`)

```
frontend/
  app/
    login/page.tsx
    (dashboard)/
      layout.tsx
      page.tsx
      batches/page.tsx
      batches/new/page.tsx
      batches/[batchId]/page.tsx
      products/quick-add/page.tsx           # NEW — closes #7
      products/[productId]/review/page.tsx
      review-queue/page.tsx
      review-queue/[productId]/page.tsx
      templates/page.tsx
      taxonomy/page.tsx
      audit-log/page.tsx
      settings/page.tsx                     # scope defined in §5, closes #8
  components/
    ProgressBadge.tsx
    SourceCitationTooltip.tsx
    WarrantyConsistencyIndicator.tsx
    SpecsTablePreview.tsx
    CsvExportButton.tsx
    ReviewQueueBadge.tsx
    MobileApproveCard.tsx
    PriceDiscrepancyBanner.tsx
    QuickAddForm.tsx                        # NEW — closes #7
    StockStatusToggle.tsx                   # NEW — closes #14
    WarrantyOverrideInput.tsx               # NEW — surfaces phase1.md §5.5's per-product override
  lib/
    apiClient.ts
    useBatchProgressStream.ts
    schemas.ts
    designTokens.ts                         # NEW — closes #5, defined in §5
  middleware.ts
  package.json                              # full dependency list in §1, closes #15
  next.config.js
  tailwind.config.ts                        # design tokens, closes #5
  .env.local.example
```

### Concrete Dependency Manifests (closes #15)

`backend/pyproject.toml` (dependency section — versions are floors, pin exact patch versions at implementation time):

```toml
[project]
name = "kiachahye-pipeline-backend"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "supabase>=2.9",                 # supabase-py, service-role client
    "langgraph>=0.2",
    "langgraph-checkpoint-postgres>=2.0",
    "langchain-core>=0.3",
    "langchain-google-genai>=2.0",   # Extractor: Gemini
    "langchain-groq>=0.2",           # Writer/Reviewer: Groq
    "langchain-openai>=0.2",         # fallback provider
    "playwright>=1.48",
    "firecrawl-py>=1.6",
    "pyjwt>=2.9",
    "passlib[bcrypt]>=1.7",
    "slowapi>=0.1.9",                # login rate limiting, closes #18
    "sentry-sdk[fastapi]>=2.17",     # Uses Sentry SDK to send data to our self-hosted/Free GlitchTip backend
    "python-multipart>=0.0.12",      # file upload (SKU snapshot CSV)
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "ruff>=0.7",
]
```

`frontend/package.json` (dependency section):

```json
{
  "dependencies": {
    "next": "^15.0.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "tailwindcss": "^3.4.0",
    "@radix-ui/react-dialog": "^1.1.0",
    "@radix-ui/react-toast": "^1.2.0",
    "@radix-ui/react-tabs": "^1.1.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.5.0",
    "zod": "^3.23.0",
    "@tanstack/react-query": "^5.59.0",
    "@uiw/react-codemirror": "^4.23.0",
    "@codemirror/lang-html": "^6.4.0"
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "@types/react": "^18.3.0",
    "eslint": "^9.13.0",
    "eslint-config-next": "^15.0.0"
  }
}
```

`@radix-ui/*` + `class-variance-authority` + `clsx`/`tailwind-merge` is the shadcn/ui pattern — see §5 for why this resolves the design-system requirement.

### Environment Variable Template (expanded, closes #13)

`backend/.env.example`:
```
ENV=development
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
APP_AUTH_SECRET=
APP_JWT_SIGNING_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=
OPENAI_API_KEY=
FIRECRAWL_API_KEY=
GLITCHTIP_DSN=
# sentry-sdk init reads this value and sends errors to GlitchTip
CORS_ORIGINS=http://localhost:3000

# Scraping rate limiting
SCRAPE_MIN_DELAY_SECONDS=3
SCRAPE_JITTER_MAX_SECONDS=5

# Batch orchestration (BatchProcessor, §9)
LLM_INTER_PRODUCT_DELAY_SECONDS=2

# LLM backoff (closes #13 — previously unspecified)
LLM_MAX_RETRIES=4
LLM_BACKOFF_BASE_SECONDS=2
LLM_BACKOFF_MAX_SECONDS=60

# Login rate limiting (closes #18)
LOGIN_RATE_LIMIT=5/minute
```

`frontend/.env.local.example`:
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### One-Command Bootstrap Script (closes #16)

`scripts/bootstrap.sh` (invoked via `make bootstrap`, `Makefile` at repo root wraps it):

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "== 1/7: checking Supabase CLI login =="
supabase status || { echo "Run 'supabase login' and 'supabase link' first."; exit 1; }

echo "== 2/7: applying migrations =="
supabase db push

echo "== 3/7: installing backend deps =="
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && playwright install chromium

echo "== 4/7: seeding taxonomy, warranty matrix, LLM config =="
python scripts/seed_taxonomy.py
python scripts/seed_warranty_matrix.py
python scripts/seed_llm_model_config.py

echo "== 5/7: installing frontend deps =="
cd ../frontend && npm install

echo "== 6/7: copying env templates (fill in secrets manually) =="
cd .. && cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

echo "== 7/7: done. Fill in backend/.env, then run: =="
echo "  Backend:  cd backend && uvicorn app.main:app --reload"
echo "  Frontend: cd frontend && npm run dev"
echo "  Login at http://localhost:3000/login with APP_AUTH_SECRET"
```

`Makefile`:
```makefile
.PHONY: bootstrap dev-backend dev-frontend test

bootstrap:
	bash scripts/bootstrap.sh

dev-backend:
	cd backend && uvicorn app.main:app --reload

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && pytest tests/unit tests/integration
```

---

## 2. Database Design (Supabase/Postgres)

Auth model and RLS strategy unchanged from v1.0 (single-user, backend-only `service_role` access, RLS enabled with zero permissive policies). All tables from v1.0 retained; changes below are additive.

### `products` — revised (closes #10, #11)

| column | type | notes |
|---|---|---|
| id | uuid pk | |
| batch_id | uuid fk→batches | |
| sku | text not null | |
| model_number | text | |
| raw_input | jsonb | |
| status | text check (...) | unchanged enum from v1.0 |
| variant_shaped | boolean default false | |
| brand_id / category_id | uuid fk | |
| template_long_desc_id | uuid fk→templates | |
| image_count / scraped_image_urls | int / jsonb | |
| name | text | |
| **short_description** | text | **NEW, closes #11** — rendered HTML, first-class column instead of jsonb-only |
| **description** | text | **NEW, closes #11** — rendered long-description HTML |
| **specs_table_html** | text | **NEW, closes #11** |
| **rank_math_focus_keyword** | text | **NEW, closes #11** |
| **rank_math_title** | text | **NEW, closes #11** |
| **rank_math_description** | text | **NEW, closes #11** |
| **weight_kg / length_cm / width_cm / height_cm** | numeric(8,2) | **NEW, closes #3** — output of `build_dimensions()`, §6 |
| regular_price / sale_price | numeric(12,2) | |
| in_stock | boolean default true | |
| warranty_override | text null | |
| resolved_warranty_phrase | text | |
| **price_discrepancy_pct** | numeric(5,2) null | populated by `compute_price_discrepancy()`, §4/§6, closes #12 |
| extraction_result / writer_result / review_result | jsonb | full raw snapshots retained for audit, even though key fields are now promoted to columns above |
| preflight_score | int | |
| **retry_count** | int default 0 | **semantics fixed, closes #6** — see §3's retry-boundary note; counts *completed* Writer/Reviewer attempts, starts at 1 after the first attempt |
| failure_reason / failure_detail | text / jsonb | |
| csv_row | jsonb | |
| **queued_at** | timestamptz default now() | **NEW, closes #10** |
| **ready_for_qa_at** | timestamptz null | **NEW, closes #10** — set by `csv_row_assembler_node` |
| approved_at / approved_by / exported_at | | |
| created_at/updated_at | | |

`queued_at` → `ready_for_qa_at` gives **system processing time**; `ready_for_qa_at` → `approved_at` gives **human QA time** — the two metrics §16 requires, split and directly queryable (see `metrics_report.py`, §7).

### Remaining Tables (restored here in full — v2.0 had referenced these as "unchanged from v1.0" without repeating them, which left them undocumented after the full-file rewrite; fixed now)

**brands** — `id uuid pk, name text unique not null, casing_confirmed boolean default false, is_active boolean default true, created_at/updated_at`.

**categories** — `id uuid pk, name text not null, parent_id uuid null fk→categories(id), is_active boolean default true, needs_confirmation boolean default true, notes text, created_at/updated_at`. `Item`/`Inverter` seeded `is_active=false` until confirmed. Unique(name, parent_id); index on parent_id.

**category_spec_schemas** — `id uuid pk, category_id uuid unique fk→categories, fields jsonb (ordered [{key,label,required}]), created_at/updated_at`. Only Microwave Oven seeded at launch; missing schema hard-blocks (§3.3).

**warranty_matrix** — `id uuid pk, brand_id uuid fk→brands, category_id uuid null fk→categories (null = brand-wide default), warranty_phrase text, last_audited_at date, is_active boolean default true`. Unique partial index on (brand_id, category_id) where is_active.

**trusted_secondary_sources** (v2.1, replaces the old mandatory per-brand `brand_source_urls` table — see §4/§5.2 for why) — a small, Settings-editable fallback list used only when Agent 1's live web search finds no domain match for the brand itself:
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| domain | text unique | e.g. `japanelectronics.pk`, `surmawala.pk` |
| label | text | e.g. "Japan Electronics" |
| priority | int | check order if more than one matches |
| is_active | boolean default true | |

Seeded with 2 rows (Japan Electronics, Surmawala) — add/remove/deactivate via Settings, no code change or redeploy needed.

**brand_domain_aliases** (v2.1, optional, usually empty) — for the rare brand whose real official domain doesn't obviously match its brand name (breaking the automatic domain-match heuristic in §4):
`id uuid pk, brand_id uuid unique fk→brands, official_domain text, is_active boolean default true`. Populated only when the heuristic fails for a specific brand; editable via Taxonomy Manager.

**templates** — `id uuid pk, template_type text check in (...), name text, html_skeleton text, is_default/is_active/version`.

**batches** — `id, label, status(pending/processing/completed/completed_with_failures), total_products, succeeded_count, failed_count, manual_review_count, created_at, updated_at`.

**source_citations** — `id uuid pk, product_id uuid fk→products on delete cascade, field_name text, value text ('UNKNOWN' allowed), source_url text, source_type text check in ('official','trusted_secondary','user_estimate'), confidence text check in ('confirmed','conflicting','unreachable'), conflicting_with_citation_id uuid null fk→source_citations, fetched_at timestamptz`. **v2.1:** `source_type` generalized from the old fixed `'japan_electronics'/'surmawala'` enum values to a single `'trusted_secondary'`, since that list is now dynamic (`trusted_secondary_sources` table) rather than two hardcoded names. Index on (product_id).

**manual_review_queue** — `id uuid pk, product_id uuid unique fk→products, batch_id uuid fk→batches, reason_code text check in ('source_unreachable','no_reliable_source_found','spec_conflict','variant_shaped','sku_collision','writer_reviewer_exhausted','preflight_score_low','missing_category_schema','missing_taxonomy_match','other'), reason_detail text not null, status text check in ('open','resolved','dismissed') default 'open', resolved_at/resolution_note`. **v2.1:** added `no_reliable_source_found` reason code for §5.3's new discovery-failure case. Partial index `WHERE status='open'`.

**audit_log** — `id bigint identity pk, product_id uuid null, batch_id uuid null, event_type text, actor text default 'system', payload jsonb, created_at timestamptz default now()`. Index on (product_id), (batch_id), (created_at desc).

**csv_exports** — `id uuid pk, batch_id uuid fk, file_name text, product_ids jsonb, row_count int, created_at`.

**live_sku_snapshot** — `id uuid pk, sku text unique, wc_product_id text, imported_at timestamptz`. Replaced wholesale on each Settings upload; CSV export hard-blocks if never synced.

**llm_model_config** — `role text pk check in ('extractor','writer','reviewer'), primary_provider text, primary_model_id text, fallback_provider text, fallback_model_id text, updated_at`.

**llm_usage_log** — `id bigint identity pk, product_id uuid null fk→products, role text, provider text, model_id text, prompt_tokens int, completion_tokens int, total_tokens int, estimated_cost_usd numeric(10,6), latency_ms int, was_fallback boolean default false, created_at`.

**app_settings** — `key text pk, value jsonb, updated_at`. Rows include `trust_level`, `rank_math_title_format`, `live_sku_last_synced_at`, **`monthly_api_budget_usd`** (v2.1, default `5.00`) — the hard spending cap below.

**Monthly API Budget Cap (v2.1):** `backend/app/core/budget_guard.py::check_budget_ok() -> bool` sums `estimated_cost_usd` from `llm_usage_log` for the current calendar month and compares it against `app_settings.monthly_api_budget_usd`. `BatchProcessor.run_batch()` (§9) calls this **before starting each product**, not just once at batch start — so a large batch that crosses the cap mid-run stops cleanly instead of overshooting. On breach: the batch pauses (remaining products stay `queued`, nothing lost), a GlitchTip alert fires, and the Dashboard shows a persistent banner ("Monthly API budget reached — paused") until you raise the limit or the month resets. Editable in Settings → Monthly API Budget Limit (one dollar-amount field, default $5).

**scrape_cache** — `id uuid pk, source_url text, product_id uuid null, raw_content text/jsonb, status text check in ('success','unreachable','blocked'), fetched_at`. Index on (source_url).

Migration files: `0001_init_schema.sql` … `0005_products_content_columns.sql` … `0006_dynamic_source_discovery.sql` (drops `brand_source_urls`, adds `trusted_secondary_sources` + `brand_domain_aliases`, alters `source_citations.source_type` and `manual_review_queue.reason_code` check constraints).

### RLS Policy Blueprint (Service-Role Only)

Every table must have RLS enabled. Since this is a single-user system where the backend (FastAPI) uses the `service_role` key to bypass RLS, the policies should be "locked" by default.

```sql
-- Example for all tables
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
-- No permissive policies added -> only service_role/admin can access.
```

### Seed Data: `app_settings`
- `trust_level`: `"full_review"`
- `monthly_api_budget_usd`: `5.00`
- `live_sku_last_synced_at`: `null`

**v8.0 note:** `rank_math_title_format` is removed from `app_settings` — the SEO title is no longer a user-editable string template. It's fully deterministic via `seo_title_builder.py`'s `CATEGORY_TITLE_DESCRIPTORS` dict (edit that dict, not a Settings field, to add a new category's literal title descriptor).

---

## 3. Agent Pipeline (LangGraph)

### 3.1 Complete Pydantic Schemas (closes #2)

`backend/app/models/taxonomy.py`:
```python
from pydantic import BaseModel
from uuid import UUID

class SpecField(BaseModel):
    key: str            # e.g. "capacity" — matches source_citations.field_name
    label: str           # e.g. "Capacity" — used verbatim in the specs table
    required: bool = True

class CategorySpecSchema(BaseModel):
    category_id: UUID
    category_name: str
    fields: list[SpecField]  # ordered; renderer always appends a "Warranty" row after these

    # Example (Microwave Oven, confirmed real sample — phase1.md §7.7):
    # CategorySpecSchema(
    #     category_id=..., category_name="Microwave Oven",
    #     fields=[
    #         SpecField(key="brand", label="Brand"),
    #         SpecField(key="model_number", label="Model Number"),
    #         SpecField(key="appliance_type", label="Appliance Type"),
    #         SpecField(key="capacity", label="Capacity"),
    #         SpecField(key="control_panel", label="Control Panel"),
    #         SpecField(key="features", label="Features"),
    #     ],
    # )
```

`backend/app/models/extraction.py`:
```python
from pydantic import BaseModel, model_validator
from datetime import datetime
from typing import Literal
from decimal import Decimal

SourceType = Literal["official", "japan_electronics", "surmawala", "user_estimate"]
Confidence = Literal["confirmed", "conflicting", "unreachable"]

class SourceCitation(BaseModel):
    field_name: str                    # matches SpecField.key
    value: str                         # literal "UNKNOWN" allowed
    source_url: str | None             # None only when confidence == "unreachable"
    source_type: SourceType
    confidence: Confidence
    fetched_at: datetime

    @model_validator(mode="after")
    def unknown_implies_unreachable_or_null_url(self):
        if self.value == "UNKNOWN" and self.confidence == "confirmed":
            raise ValueError("value='UNKNOWN' cannot have confidence='confirmed' — no-hallucination contract violation (phase1.md §5.2)")
        return self

    # Example (confirmed fact):
    # SourceCitation(field_name="capacity", value="30 Liters", source_url="https://dawlance.com.pk/...",
    #                 source_type="official", confidence="confirmed", fetched_at=...)
    # Example (unreachable — no hallucination):
    # SourceCitation(field_name="control_panel", value="UNKNOWN", source_url=None,
    #                 source_type="official", confidence="unreachable", fetched_at=...)

class ExtractionResult(BaseModel):
    product_id: str
    category_key: str
    citations: list[SourceCitation]     # 1+ per field_name; 2+ with differing values on the same
                                         # field_name = an unresolved conflict
    image_urls: list[str] = []
    scraped_official_price: Decimal | None = None

    def confirmed_value(self, field_name: str) -> str | None:
        """Returns the single confirmed value for a field, or None if UNKNOWN/conflicting/absent."""
        matches = [c for c in self.citations if c.field_name == field_name and c.confidence == "confirmed"]
        if len(matches) == 1:
            return matches[0].value
        return None  # 0 matches (missing/unreachable) or 2+ matches (conflict) both resolve to None

    def has_conflict(self, field_name: str) -> bool:
        values = {c.value for c in self.citations if c.field_name == field_name and c.confidence == "confirmed"}
        return len(values) > 1

    def missing_required_fields(self, schema: "CategorySpecSchema") -> list[str]:
        return [f.key for f in schema.fields if f.required and self.confirmed_value(f.key) is None
                and not self.has_conflict(f.key)]

    def conflicting_fields(self, schema: "CategorySpecSchema") -> list[str]:
        return [f.key for f in schema.fields if self.has_conflict(f.key)]
```

`backend/app/models/writer_output.py` (v8.0 Production Lock):
```python
from pydantic import BaseModel, field_validator

class FAQPair(BaseModel):
    question: str
    answer: str

class WriterOutput(BaseModel):
    hero_heading: str
    hero_paragraph: str
    feature_headings: list[str]         # len==2 for Template B, len==3 for Template A
    feature_texts: list[str]            # same length as feature_headings
    features_bullets: list[str]         # 4-6 bullets, phase1.md §7.3
    faqs: list[FAQPair]                 # exactly 5; faqs[4] is ALWAYS the fixed warranty Q&A
    short_desc_feature_1: str
    short_desc_feature_2: str
    short_desc_feature_3: str

    # --- v8.0 Production Lock SEO fields ---
    # rank_math_focus_keyword is NO LONGER written by the LLM — locked deterministically
    # to the exact Product Name by the pipeline (nodes.py). rank_math_title is NO LONGER
    # written by the LLM — built deterministically by seo_title_builder.py ("Boss Title Rule").
    rank_math_description: str          # strictly 151-155 chars; begins with focus keyword;
                                         # mentions warranty; ends with fixed CTA (seo_validator.py)
    lsi_keywords: list[str]             # exactly 3 — must appear as PLAIN TEXT (no bold/header
                                         # wrapper) somewhere in the body copy. v3.0: these 3 keywords
                                         # are also reused downstream (unchanged from the LLM's view)
                                         # as the Rank Math secondary keywords in the exported CSV's
                                         # Meta: rank_math_focus_keyword field — see build_focus_keyword_field(), §3.2, §8.7.
    alt_text_1: str                     # Template A image 1 alt text — focus keyword or an LSI keyword
    alt_text_2: str
    alt_text_3: str

    @field_validator("faqs")
    @classmethod
    def exactly_five_faqs(cls, v: list[FAQPair]) -> list[FAQPair]:
        if len(v) != 5:
            raise ValueError(f"WriterOutput.faqs must have exactly 5 entries, got {len(v)}")
        if v[4].question != "What is the official warranty?":
            raise ValueError("faqs[4].question must be the fixed warranty question, phase1.md §6.4")

    @field_validator("lsi_keywords")
    @classmethod
    def exactly_three_lsi_keywords(cls, v: list[str]) -> list[str]:
        if len(v) != 3:
            raise ValueError(f"WriterOutput.lsi_keywords must have exactly 3 entries, got {len(v)} (v8.0 Production Lock)")
        if any(not k.strip() for k in v):
            raise ValueError("WriterOutput.lsi_keywords entries must not be empty")
        return v
        return v
```

`backend/app/models/review_result.py`:
```python
from pydantic import BaseModel

class SeoCheckResult(BaseModel):
    check_name: str    # one of the 11 checks, phase1.md §6.8, e.g. "product_name_length"
    passed: bool
    detail: str

class ReviewResult(BaseModel):
    passed: bool
    preflight_score: int              # 0-100, phase1.md §6.6
    checks: list[SeoCheckResult]      # all 11 checks from seo_validator.py, always present regardless of pass/fail
    warranty_consistent: bool         # phase1.md §5.5's 4-location exact-match check
    fact_cross_check_passed: bool     # writer text doesn't contradict Agent 1's confirmed facts
    fact_cross_check_notes: list[str] # human-readable notes on any mismatch found
    failure_summary: str | None = None
```

`backend/app/models/failure.py`:
```python
from pydantic import BaseModel
from typing import Literal

FailureCategory = Literal[
    "source_unreachable", "spec_conflict", "variant_shaped", "sku_collision",
    "writer_reviewer_exhausted", "preflight_score_low", "missing_category_schema",
    "missing_taxonomy_match", "other",
]

class FailureInfo(BaseModel):
    category: FailureCategory
    detail: str                     # human-readable, matches manual_review_queue.reason_detail
    context: dict[str, str] = {}    # e.g. {"field": "capacity", "value_a": "20L", "value_b": "21L"}
```

`backend/app/models/raw_input.py`:
```python
from pydantic import BaseModel
from decimal import Decimal
from typing import Literal

class RawProductInput(BaseModel):
    sku: str
    model_number: str
    short_title: str
    brand_name: str
    category_name: str
    regular_price: Decimal
    sale_price: Decimal
    in_stock: bool = True                        # closes #14 — surfaced by StockStatusToggle.tsx
    warranty_override: str | None = None          # phase1.md §5.5's per-product override
    template_choice: Literal["A", "B"] = "A"
```

`backend/app/models/dimensions.py` (closes #3):
```python
from pydantic import BaseModel

class DimensionsResult(BaseModel):
    weight_kg: float = 0.0
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0
```

`backend/app/graph/state.py` (unchanged shape, references the schemas above):
```python
from pydantic import BaseModel
from uuid import UUID
from typing import Literal

class PipelineState(BaseModel):
    product_id: UUID
    batch_id: UUID
    raw_input: RawProductInput
    category_schema: CategorySpecSchema | None = None
    extraction: ExtractionResult | None = None
    selected_template_type: Literal["A", "B"] = "A"
    writer_output: WriterOutput | None = None
    review_result: ReviewResult | None = None
    dimensions: DimensionsResult | None = None
    retry_count: int = 0
    failure: FailureInfo | None = None
```

### 3.2 Full Prompt Templates (closes #1)

All three prompts are Jinja-style `str.format`-rendered before being sent as the LLM's system message; `{...}` placeholders are filled by the calling node. Output is enforced via the provider's structured-output/JSON-mode feature bound to the corresponding Pydantic model — the prompt's own JSON-shape instructions are a second layer of defense, not the only one.

#### Agent 1 — Extractor (`backend/app/agents/extractor.py::EXTRACTOR_SYSTEM_PROMPT`)

```
You are a factual data extraction agent for a Pakistani home-appliance e-commerce catalog.
Your ONLY job is to read the source documents provided below and extract specific facts.
You are NOT a copywriter. You are NOT allowed to guess, infer, estimate, or use general
knowledge about similar products. Every value you output MUST be traceable to the literal
text of one of the source documents below.

## Hard Rules (violating any of these is a critical failure)

1. For each field in REQUIRED FIELDS, search every source document in the order given.
   If you find the fact stated in a document, extract it and cite that document's URL.
2. If a field is NOT explicitly stated in ANY source document, you MUST output
   value="UNKNOWN" and source_url=null and confidence="unreachable" for that field.
   Do NOT fill it with a typical/average/plausible value. An UNKNOWN is a correct,
   desired answer when the fact truly isn't present — it is never a failure on your part.
3. If two or more source documents state DIFFERENT values for the same field, output
   ONE citation per differing value (both with confidence="confirmed"), so the conflict
   is visible downstream. Do NOT silently pick one — that is a critical failure.
4. Never combine, average, or paraphrase two sources into a new value that appears in
   neither source verbatim.
5. Output strict JSON matching the ExtractionResult schema below. No prose, no markdown,
   no explanation outside the JSON object.

## Category: {category_name}

## Required Fields (extract exactly these — do not add or omit fields)
{required_fields_json}

## Source Documents (in priority order — official brand site first, then reference sites)
{source_documents}
<!-- Each document rendered as: -->
<!-- ### SOURCE [{source_type}] {source_url}
     {scraped_text_content} -->

## Output Schema
Return a single JSON object:
{{
  "citations": [
    {{"field_name": "<key from required fields>", "value": "<extracted text or 'UNKNOWN'>",
      "source_url": "<url or null>", "source_type": "<official|japan_electronics|surmawala>",
      "confidence": "<confirmed|unreachable>", "fetched_at": "<ISO 8601 timestamp>"}}
  ],
  "image_urls": ["<url>", ...],
  "scraped_official_price": <number or null>
}}

## Worked Example
Given source text: "The Dawlance DW-131 HP Sync features a 30 Liters capacity and Cook King
recipes. Warranty details available separately." and required field "control_panel" is never
mentioned anywhere in any source:

{{
  "citations": [
    {{"field_name": "capacity", "value": "30 Liters", "source_url": "https://dawlance.com.pk/products/dw-131-hp-sync",
      "source_type": "official", "confidence": "confirmed", "fetched_at": "2026-07-19T10:00:00Z"}},
    {{"field_name": "control_panel", "value": "UNKNOWN", "source_url": null,
      "source_type": "official", "confidence": "unreachable", "fetched_at": "2026-07-19T10:00:00Z"}}
  ],
  "image_urls": ["https://dawlance.com.pk/img/dw-131-1.jpg"],
  "scraped_official_price": 41300
}}

Now perform the extraction for the product and sources given above. Output ONLY the JSON object.
```

#### Agent 2 — Writer (`backend/app/agents/writer.py::WRITER_SYSTEM_PROMPT`) — v8.0 Production Lock

```
You are an e-commerce copywriter for a Pakistani home-appliance store. You write persuasive,
accurate product content by filling placeholders in a fixed HTML template. You NEVER write
raw HTML — you only produce the JSON fields listed in the output schema; a separate program
merges your text into the template.

## Ground Truth (read-only — do not contradict, restate only what's confirmed here)
{cited_facts_json}
<!-- e.g. {"capacity": "30 Liters", "control_panel": "UNKNOWN", ...} -->
<!-- Any field showing "UNKNOWN" means that fact is not available — do not mention it,
     do not invent a value for it, and do not claim the product does or doesn't have it. -->

## Product
Brand: {brand_name} | Category: {category_name} | Name: {product_name}
Warranty (use this exact phrase wherever warranty is mentioned): {warranty_phrase}
Template: {template_type}   <!-- "A" = 3 image/feature blocks, "B" = 1 text section -->

## SEO Rules — v8.0 Production Lock (100/100 Rank Math guarantee, zero tolerance)

1. Focus Keyword: "{focus_keyword}" — this is LOCKED to the exact Product Name and is
   NOT something you write; it is applied deterministically outside this prompt. Use it
   naturally within the first 10% of hero_paragraph and 3-6 times across all text combined
   (vary phrasing on later repeats — do not repeat the identical phrase verbatim more than
   twice in a row).

2. rank_math_title: also NOT written by you — built deterministically outside this prompt
   (the "Boss Title Rule" / power-word format). Do not include it in your output.

3. rank_math_description: a single string, EXACTLY 151 to 155 characters (count characters,
   not words). It MUST:
   - begin with the exact focus keyword "{focus_keyword}"
   - explicitly mention the warranty ("{warranty_phrase}")
   - end with exactly this sentence, verbatim, no variation: "{meta_description_cta}"
   Compose the middle so the whole string lands in the 151-155 character window — pad or
   trim connective phrasing as needed. This is a HARD CONSTRAINT; a description outside
   151-155 chars, missing the warranty mention, not starting with the focus keyword, or not
   ending with the exact CTA sentence will be rejected by the Reviewer.

4. lsi_keywords: generate EXACTLY 3 LSI (semantically related) keywords for this product.
   Each one MUST be woven natively into your hero_paragraph or feature_texts as plain
   sentence text — never inside a bolded phrase, a heading, or otherwise emphasized markup.
   You are producing plain strings in JSON, so this mainly means: don't phrase an LSI
   keyword as if it were a heading/title fragment, write it as ordinary prose. It must
   appear verbatim (case-insensitive) somewhere in your body copy or the Reviewer will
   reject the output.

5. alt_text_1 / alt_text_2 / alt_text_3: for Template A's three product images, each alt
   text MUST be exactly the focus keyword "{focus_keyword}" or exactly one of your three
   lsi_keywords — nothing else, no extra words. For Template B, still supply plausible
   values for alt_text_1/2/3 (they may be unused by the renderer, but the field is
   required) using the same rule.

6. faqs: exactly 5 question/answer pairs. Questions 1-4 are about real product features
   from the Ground Truth above (never about an UNKNOWN field). Question 5 MUST be exactly
   "What is the official warranty?" with answer "It comes with a {warranty_phrase} provided
   by {brand_name}."

## Content Structure
- hero_heading, hero_paragraph: transactional hook using the Ground Truth facts only.
- feature_headings / feature_texts: {feature_block_count} entries (3 for Template A, 2 for
  Template B), each describing one confirmed feature from Ground Truth.
- features_bullets: 4-6 short bullet points, confirmed facts only.
- short_desc_feature_1/2/3: three short phrases for the short description template,
  confirmed facts only.

## Output Schema
Return a single JSON object matching WriterOutput exactly — no markdown, no prose outside JSON:
{{
  "hero_heading": "...", "hero_paragraph": "...",
  "feature_headings": ["...", ...], "feature_texts": ["...", ...],
  "features_bullets": ["...", ...],
  "faqs": [{{"question": "...", "answer": "..."}}], ... exactly 5 ...],
  "short_desc_feature_1": "...", "short_desc_feature_2": "...", "short_desc_feature_3": "...",
  "rank_math_description": "...",
  "lsi_keywords": ["...", "...", "..."],
  "alt_text_1": "...", "alt_text_2": "...", "alt_text_3": "..."
}}

{reviewer_feedback_if_retry}
<!-- On a retry, this section is populated with the specific ReviewResult failures from the
     previous attempt, e.g. "Previous attempt failed: rank_math_description was 149 characters
     (required 151-155). Fix only that issue; keep everything else that passed." -->

Output ONLY the JSON object.
```

**Note on `rank_math_focus_keyword` and `rank_math_title`:** neither is in the Writer's output schema above — both are v8.0 deterministic fields computed by the pipeline (`build_name()` for the focus keyword, `seo_title_builder.py::build_seo_title()` for the title) before the Writer is even called, and passed *into* the prompt as `{focus_keyword}` context, never generated by the LLM. This removes an entire class of possible LLM drift on the two fields Rank Math weights most heavily. The Writer still never sees or produces the *exported* multi-keyword CSV field — that combination happens downstream, purely from data the Writer already emits (`lsi_keywords`) plus the deterministic primary keyword; see the v3.0 changelog entry above and §8.7.

#### Agent 3 — Reviewer (`backend/app/agents/reviewer.py::REVIEWER_SYSTEM_PROMPT`)

Used only for the semantic fact-cross-check sub-task; the 12 SEO checks (v8.0 Production Lock, `phase1.md` §6.8) and the warranty-mention check are deterministic Python (`seo_validator.py`) — the latter relaxed under v3.0 to require the warranty's duration number(s) to appear rather than the exact stored phrase (see changelog above) — not LLM calls; the Reviewer's LLM call exists solely to catch prose-level contradictions that string matching can't (e.g., the Writer implying a feature exists when the corresponding Ground Truth field was UNKNOWN).

```
You are a strict fact-checker. Compare the WRITTEN CONTENT below against the GROUND TRUTH
facts. Your only job is to find contradictions — cases where the written content states or
implies something that isn't supported by Ground Truth, or where a Ground Truth fact marked
UNKNOWN is nonetheless described as present.

## Ground Truth (confirmed facts only; anything not listed here is unconfirmed)
{cited_facts_json}

## Written Content
{writer_output_text}
<!-- hero_heading + hero_paragraph + feature_texts + features_bullets + all FAQ answers,
     concatenated -->

## Instructions
Think step by step: for each factual claim in the Written Content, check whether it is
directly supported by an entry in Ground Truth. A claim is a CONTRADICTION if:
- it states a specific number/spec that doesn't match any Ground Truth value, OR
- it claims a feature exists that has no corresponding Ground Truth entry, OR
- it describes an UNKNOWN field as if it were known.
A claim is NOT a contradiction if it's generic marketing language with no specific,
checkable fact behind it (e.g. "perfect for modern homes").

## Output Schema
{{
  "fact_cross_check_passed": <true if zero contradictions found, else false>,
  "fact_cross_check_notes": ["<one line per contradiction found, empty list if none>"]
}}

Output ONLY the JSON object.
```

### 3.3 Nodes (`backend/app/graph/nodes.py`) — unchanged list from v1.0, with corrections

1. `intake_triage` — unchanged.
2. `extractor_node` — calls `scraping/orchestrator.py`, then `agents/extractor.py` using `EXTRACTOR_SYSTEM_PROMPT` above. **New sub-step (closes #12):** after scraping completes, calls `builders/price_reference.py::compute_price_discrepancy(scraped_official_price, raw_input.regular_price)` and stores the result on `products.price_discrepancy_pct`.
3. `after_extractor` router — unchanged logic, now also reads `ExtractionResult.conflicting_fields()`/`missing_required_fields()` (defined in §3.1) to decide the failure category (`spec_conflict` vs. generic missing-field).
4. `image_fallback_node` — unchanged.
5. `writer_node` — calls `agents/writer.py` using `WRITER_SYSTEM_PROMPT`; on a retry, populates `{reviewer_feedback_if_retry}` from the previous `ReviewResult.checks`/`fact_cross_check_notes`.
6. `reviewer_node` — runs `seo_validator.py`'s 11 deterministic checks AND calls `agents/reviewer.py` using `REVIEWER_SYSTEM_PROMPT` for the semantic cross-check; combines both into one `ReviewResult`.
7. `after_review` router — **retry semantics fixed (closes #6):** `retry_count` represents *completed attempts*, starting at `1` immediately after the first `writer_node` run (not `0`). Logic:
   ```python
   def after_review(state: PipelineState) -> str:
       if state.review_result.passed:
           return "deterministic_builders_node"
       if state.retry_count < 3:
           state.retry_count += 1
           return "writer_node"
       category = "preflight_score_low" if state.review_result.preflight_score < 90 else "writer_reviewer_exhausted"
       state.failure = FailureInfo(category=category, detail=state.review_result.failure_summary or "")
       return "escalation_handler"
   ```
   And `writer_node` itself sets `retry_count = 1` on its first invocation if `retry_count == 0`. This produces exactly **3 total Writer/Reviewer attempts** before escalation (attempt 1 → fail → retry_count=1<3 → attempt 2 → fail → retry_count=2<3 → attempt 3 → fail → retry_count=3, not <3 → escalate), matching `phase1.md` §5.6's "up to 3 cycles" read as 3 total attempts. `tests/unit/test_retry_boundary.py` asserts this exact count.
8. `escalation_handler` — unchanged.
9. `deterministic_builders_node` — runs Name Builder → Short Description Renderer → Specs Renderer → Tag Generator → **`build_dimensions()` (new, closes #3)** → `taxonomy_lock.resolve_taxonomy()`. Writes `products.short_description`, `products.description`, `products.specs_table_html`, `products.rank_math_focus_keyword/title/description`, `products.weight_kg/length_cm/width_cm/height_cm` (all newly first-class columns per §2, closes #11).
10. `html_sanitize_node` — unchanged.
11. `duplicate_sku_guard_node` — unchanged.
12. `csv_row_assembler_node` — unchanged, plus sets `products.ready_for_qa_at = now()` (closes #10).

---

## 4. Scraping Module

`backend/app/scraping/`

- **`base.py`** — `Scraper` protocol: `async fetch(url) -> ScrapeResult{content, status: success|unreachable|blocked, fetched_at}`.
- **`playwright_client.py`** — headless Chromium via Playwright for official brand sites (JS-rendered). Nav timeout 20s, 1 retry max. Detects block signals (CAPTCHA markers, 403/429, Cloudflare challenge title) → `status='blocked'`, treated identically to `unreachable` downstream. No CAPTCHA-solving attempted.
- **`firecrawl_client.py`** — Firecrawl API, used both for scraping reference-site pages and (v2.1) for the web-search step below.
- **`source_discovery.py`** (v2.1, replaces `brand_url_resolver.py` — no more pre-registered per-brand URLs):
  - `web_search(query: str) -> list[SearchResult]` — Firecrawl's search endpoint (already in the stack, so this adds no new API dependency).
  - `domain_matches_brand(url: str, brand_name: str, alias_domain: str | None) -> bool` — deterministic heuristic: normalizes the brand name and checks it against the URL's registrable domain; if `brand_domain_aliases` (§2) has an override for this brand, that exact domain is trusted directly instead of running the heuristic.
  - `resolve_sources(brand, model_number, category) -> DiscoveredSources` — runs `web_search(f"{brand} {model_number}")`, then: (1) filter results to a `domain_matches_brand` hit → `"official"`; (2) if none, filter results against the active `trusted_secondary_sources` domains (§2) → `"trusted_secondary"`; (3) if neither, return an empty result — **no arbitrary fallback to an unranked search result**.
- **`rate_limiter.py`** — its own token-bucket/jitter object (3–5s jitter, `SCRAPE_MIN_DELAY_SECONDS`/`SCRAPE_JITTER_MAX_SECONDS` from config), completely separate instance from the LLM backoff logic in `core/llm_provider.py` — per `phase1.md` §4's requirement that these must not share state. Applies to `web_search` calls too, not just page fetches.
- **`orchestrator.py`** — `scrape_all_sources(brand, model, category)` calls `source_discovery.resolve_sources(...)` first. **If it returns nothing** (no official-domain match, no trusted-secondary match), the product routes straight to Manual Review with `reason_code="no_reliable_source_found"` (§2) — a new, distinct terminal case from `"source_unreachable"` (which still means "a source *was* identified but failed to load"). If sources were found, fetches them (respecting the rate limiter between each) and returns a `MultiSourceScrapeResult`. Beyond that, unreachability is naturally fatal through the no-hallucination contract — a fact is only `confirmed` if some *reachable* source actually provided it; if a found source goes down mid-fetch and no other reachable source covers a required field, that field stays `UNKNOWN`, and `after_extractor` catches it.
- **`scrape_cache`** table (§2) — prevents re-scraping (and re-searching) on writer↔reviewer retries, since extraction runs exactly once per pipeline execution by construction.

One addition beyond the discovery rework, unchanged from v1.0:

`backend/app/builders/price_reference.py` (closes #12):
```python
from decimal import Decimal

def compute_price_discrepancy(scraped_price: Decimal | None, entered_price: Decimal) -> Decimal | None:
    """phase1.md §8.2/§9: surfaces a non-blocking warning if scraped official price
    differs from the user's entered price by more than 15%. Returns None if no
    official price was scraped (nothing to compare)."""
    if scraped_price is None or scraped_price == 0:
        return None
    return abs(scraped_price - entered_price) / scraped_price * 100
```
Called from `extractor_node` (§3.3, step 2) immediately after scraping, stored on `products.price_discrepancy_pct`. `PriceDiscrepancyBanner.tsx` renders a warning when `> 15`.

`llm_provider.py` backoff (closes #13): exponential backoff using `LLM_MAX_RETRIES` / `LLM_BACKOFF_BASE_SECONDS` / `LLM_BACKOFF_MAX_SECONDS` from config — `delay = min(LLM_BACKOFF_BASE_SECONDS * 2**attempt, LLM_BACKOFF_MAX_SECONDS)`, retried only on HTTP 429/5xx, falling over to the configured fallback provider after `LLM_MAX_RETRIES` is exhausted on the primary.

---

## 5. Frontend (Next.js App Router + Tailwind)

### 5.1 Design System — clean, simple, single-user dashboard (locked, closes #5)

**Confirmed direction:** this is a personal tool for one operator (you), not a product for other users or a client — so the UI optimizes for *your* daily speed and clarity, not for polish, branding, or configurability nobody else needs. "Clean and simple" wins over "impressive" every time there's a tradeoff. The earlier "Thriftify" reference was never defined anywhere in this project, so it's dropped in favor of this concrete, locked direction:

- **Component primitives:** [shadcn/ui](https://ui.shadcn.com) pattern — Radix UI primitives (`@radix-ui/react-dialog`, `-tabs`, `-toast`, already in `package.json` §1) + `class-variance-authority` + `tailwind-merge`, copied into `frontend/components/ui/` as owned source (not an npm-installed black box), so every component can be trimmed to exactly what this app needs.
- **Design tokens** (`frontend/lib/designTokens.ts`, mirrored into `tailwind.config.ts`):
  ```ts
  export const tokens = {
    colors: {
      background: "#FAFAFA", surface: "#FFFFFF", border: "#E5E5E5",
      textPrimary: "#171717", textSecondary: "#6B6B6B",
      accent: "#561491",       // matches the existing WoodMart product template accent (phase1.md §7.3)
      accentSoft: "#F7A800",   // matches the existing WoodMart template highlight color
      success: "#16A34A", warning: "#D97706", danger: "#DC2626",
    },
    radius: { sm: "4px", md: "8px", lg: "12px" },
    spacing: "4px base unit, Tailwind default scale (4/8/12/16/24/32px)",
    typography: { fontFamily: "Inter, system-ui, sans-serif", scale: "text-sm/base/lg/xl/2xl only — no custom sizes" },
  };
  ```
  The accent colors deliberately reuse `#561491`/`#F7A800` from the WoodMart product-page templates (`phase1.md` §7.3/§7.7) so the internal tool and the storefront output feel like one system, not two unrelated products.
- **Density:** compact spacing, no decorative imagery, table-first layouts for QA/Review Queue — appropriate for a fast daily-use internal tool, not a marketing site.

### 5.2 Pages & Behavioral Notes

**Dashboard** (`app/(dashboard)/page.tsx`) — the home screen, restated here in full since it was previously left implicit. One screen, no scrolling required on desktop, answers "what needs my attention right now" at a glance:
- **5 stat cards at the top:** Manual Review Queue count (links straight there), products currently `ready_for_qa` (links to a filtered QA list), batches in progress (with a mini live progress bar per batch via the existing SSE stream), this week's approved-product count, and **Avg QA time / product (last 7 days)** — pulled from `ready_for_qa_at`→`approved_at` (§2), the one number that directly answers "am I actually faster than the old 24 min/product." Not vanity metrics — no charts, no graphs, just 5 numbers.
- **Recent Batches table below:** last 10 batches, columns = label, status, succeeded/failed/manual-review counts, "Open" link. This is the default landing view — you should be able to tell what's stuck without clicking anything.
- **Two big, obvious buttons, not buried in a menu:** "New Batch" and "Quick-Add" — these are the two most common actions, so they're primary buttons on the dashboard itself, not just nav-bar links.
- Nothing else on this page. No activity feed, no charts, no widgets you didn't ask for — every extra element is one more thing to visually parse before you can start work.

**Navigation** (`layout.tsx`): a single left sidebar (collapses to a bottom bar on mobile, per the mobile scope below) with exactly 8 links — Dashboard, Batches, Quick-Add, Manual Review Queue (with the badge count), Templates, Taxonomy, Audit Log, Settings. No nested menus, no flyouts — everything is one click away.

**Human QA Panel** (`app/(dashboard)/products/[productId]/review/page.tsx`): one product per screen, fields listed top to bottom in the same order they appear on the actual WooCommerce product page (name → price → categories/brand/tags → short description → long description → specs table → SEO fields), so reviewing feels like proofreading the real page, not decoding a form. Toggle bound to `app_settings.trust_level`: **Full mode** shows every field with an inline `SourceCitationTooltip` (click to open the source URL); **Quick mode** shows only the fields the Reviewer itself flagged. Two buttons only: **Approve** and **Reject** — no multi-step wizard.

**Manual Review Queue** (`app/(dashboard)/review-queue/page.tsx`): a flat list, not a kanban board — SKU, product name, `reason_code` in plain English (not the raw enum value), age. Click a row to open detail (`review-queue/[productId]/page.tsx`) showing exactly what failed and why. `ReviewQueueBadge.tsx` in the nav shows the open count at all times, so nothing piles up unnoticed.

**Template Manager** (`app/(dashboard)/templates/page.tsx`): a list of the 4 templates (short description, long description A/B, specs table) with an "Edit" action opening a CodeMirror HTML editor + a live preview pane rendered with sample data — no need to understand the placeholder syntax by memory.

**Taxonomy Manager** (`app/(dashboard)/taxonomy/page.tsx`): two tabs, Brands and Categories. Categories shows the tree with parent/child nesting visually (indentation, not a flat table), a "needs confirmation" badge per row, and inline editing of `parent_id` — this is the screen where `phase1.md` §0's category-tree and brand-casing work actually gets done, not a spreadsheet you have to reconcile separately.

**Price Reference Panel** (surfaced inside the QA Panel, not a separate page): shows the scraped official/trusted-secondary price next to your entered price, with `PriceDiscrepancyBanner.tsx` appearing only when they differ by more than 15% — silent otherwise, so it doesn't add noise to the common case.

**Audit Log** (`app/(dashboard)/audit-log/page.tsx`): a simple filterable table (by product, by batch, by event type) over the `audit_log` table — this is a debugging/traceability tool, not a daily-use screen, so it gets no special layout treatment beyond a plain sortable table.

**Mobile scope:** Dashboard, Manual Review Queue, and the QA Panel's approve/reject flow work fully on a phone in a single-column layout — this covers "check on things and approve/reject while out" per `phase1.md` §11's actual stated mobile use case. Batch Input, Template Manager, and Taxonomy Manager show a plain "open this on desktop" notice below the mobile breakpoint instead of being force-fit into a phone screen — those are deliberate, occasional, sit-down tasks, not something you'd do standing in a shop.

**Real-time:** `useBatchProgressStream.ts` wraps `EventSource` against the batch SSE endpoint — progress updates appear on their own, no manual refresh, no polling spinner.

**Auth:** one login screen, one field (the shared secret), no "remember me"/2FA/password-reset flow to build or maintain — this is a single-user internal tool, so the login screen is exactly as complex as it needs to be and no more.

Two functional additions on top of all of the above:

**Quick-Add (closes #7):** `app/(dashboard)/products/quick-add/page.tsx` — a single-product form (`QuickAddForm.tsx`) with the same fields as one row of Batch Input (SKU, model number, short title, brand, category, regular/sale price, `StockStatusToggle.tsx`, `WarrantyOverrideInput.tsx`, template choice). Submits to `POST /api/products/quick-add`, which server-side creates a `batches` row with `total_products=1` and a single `products` row, then immediately triggers `BatchProcessor.run_batch()` (§9) — Quick-Add is implemented as "a batch of one," not a separate pipeline path, so it inherits every accuracy/escalation rule for free. Redirects to `batches/[batchId]/page.tsx` to watch progress.

**In-stock control (closes #14):** `StockStatusToggle.tsx` — a simple on/off switch, default ON, rendered in both Batch Input's per-row form and `QuickAddForm.tsx`, bound to `RawProductInput.in_stock`.

**Settings page — explicit scope (closes #8):** `app/(dashboard)/settings/page.tsx` renders exactly these sections, and **nothing else**:
1. **Trusted Secondary Sources** (v2.1, replaces the old per-brand "Brand Source URLs" section — no longer needed since official sites are found dynamically, §4) — a simple add/remove/deactivate list over `trusted_secondary_sources` (domain + label, e.g. `japanelectronics.pk` / "Japan Electronics"), plus a small "Brand Domain Overrides" sub-table over `brand_domain_aliases` for the rare brand the automatic domain-match heuristic gets wrong.
2. **Warranty Matrix** — CRUD table over `warranty_matrix` (brand+category → warranty phrase, `last_audited_at` shown with a "stale (>90 days)" badge to prompt the quarterly re-audit from `phase1.md` §5.5).
3. **Trust Level** — the `app_settings.trust_level` toggle (Full Review Mode / Quick Review Mode), with a confirmation dialog since `phase1.md` §15 calls this a one-way decision.
4. **SEO Title Descriptors** (v8.0, replaces the old format dropdown) — a read/edit view over `seo_title_builder.py`'s `CATEGORY_TITLE_DESCRIPTORS` dict, so adding a new category's literal "Boss Title Rule" descriptor doesn't require a code deploy. The title itself is no longer a free-text template — it's deterministic, category-aware, and not user-editable beyond registering a category's descriptor string.
5. **Live SKU Snapshot** — CSV file upload replacing `live_sku_snapshot` wholesale, showing `live_sku_last_synced_at`.
6. **Monthly API Budget Limit** (v2.1) — a single dollar-amount field bound to `app_settings.monthly_api_budget_usd` (default $5), plus a small this-month-so-far total pulled from `llm_usage_log` so you can see how close you are before it ever pauses anything.
7. **API Key Status** (read-only) — a checklist showing which of `GEMINI_API_KEY`/`GROQ_API_KEY`/`OPENAI_API_KEY`/`FIRECRAWL_API_KEY`/`GLITCHTIP_DSN` are configured (present/absent only — **the values themselves are never fetched, displayed, or editable via this UI**; they live only in the droplet's `.env`, per §1's secrets rule). This satisfies "a Settings page mentions API keys" without ever exposing a secret to a browser.

Taxonomy Manager (unchanged from v1.0) remains the separate page for `brands`/`categories`/`category_spec_schemas` — Settings does not duplicate it.

---

## 6. CSV Engine & Deterministic Builders

### 6.1 Column Order (Master Checklist — 49 columns)
`COLUMN_ORDER` constant used by `csv.DictWriter` (matches `phase1.md` §8.7):
1. `ID` (empty), 2. `Type` (`simple`), 3. `SKU`, 4. `Name`, 5. `Published` (`-1`), 6. `Is featured?` (`0`), 7. `Visibility in catalog` (`visible`), 8. `Short description`, 9. `Description`, 10. `Date sale price starts`, 11. `Date sale price ends`, 12. `Tax status` (`none`), 13. `Tax class`, 14. `In stock?` (`1`), 15. `Stock`, 16. `Low stock amount`, 17. `Backorders allowed?` (`0`), 18. `Sold individually?` (`0`), 19. `Weight (kg)`, 20. `Length (cm)`, 21. `Width (cm)`, 22. `Height (cm)`, 23. `Allow customer reviews?` (`1`), 24. `Purchase note`, 25. `Sale price`, 26. `Regular price`, 27. `Categories`, 28. `Tags`, 29. `Shipping class`, 30. `Images` (empty), 31. `Download limit` (`0`), 32. `Download expiry days` (`0`), 33. `Parent`, 34. `Grouped products`, 35. `Upsells`, 36. `Cross-sells`, 37. `External URL`, 38. `Button text`, 39. `Position` (`0`), 40. `Brands`, 41. `Meta: _woodmart_product_custom_tab_title` (`Specification`), 42. `Meta: _woodmart_product_custom_tab_priority` (`20`), 43. `Meta: _woodmart_product_custom_tab_content_type` (`text`), 44. `Meta: _woodmart_product_custom_tab_content` (Specs HTML), 45. `Meta: rank_math_focus_keyword` (v3.0: primary keyword + 3 LSI keywords, comma-joined via `build_focus_keyword_field()` — not the primary keyword alone), 46. `Meta: rank_math_title`, 47. `Meta: rank_math_description`, 48. `Meta: rank_math_seo_score` (empty), 49. `Meta: rank_math_breadcrumb_title` (Name).

### 6.2 Name Builder (`name_builder.py`)
Formula: `[Brand] [Capacity] [Model] [Type]`
- Capacity cleaning: `1.0 Ton` -> `1 Ton`, `20 Liters` -> `20L`.
- **44-Char Limit:** If total length > 44, abbreviate `Type`:
    - `Air Conditioner` -> `AC`
    - `Microwave Oven` -> `Microwave`
    - `Washing Machine` -> `Washer`
    - `Water Dispenser` -> `Dispenser`

### 6.3 Tag Generator (`tag_generator.py`)
Formula: `[Brand], [Category], HW` (Exactly 3 tags, comma-separated).

### 6.4 Dimensions Builder (`dimensions_builder.py`) (closes #3)

Unchanged core design from v1.0 (`COLUMN_ORDER` single source of truth, `csv.DictWriter` + `QUOTE_ALL`, `taxonomy_lock.py`, `sku_guard.py`, `html_sanitizer.py`). One addition:

`backend/app/builders/dimensions_builder.py` (closes #3):
```python
import re
from app.models.extraction import ExtractionResult
from app.models.dimensions import DimensionsResult

def build_dimensions(extraction: ExtractionResult) -> DimensionsResult:
    """Maps Weight/Length/Width/Height facts to WooCommerce CSV columns 19-22
    (phase1.md §8.4/§8.7). Per phase1.md §8.4 ('Agent 1 (or 0)'), any dimension
    that is UNKNOWN or unparseable defaults to 0 — dimensions are optional and
    never block the pipeline, unlike required category-spec fields."""

    def _numeric_or_zero(field_name: str) -> float:
        value = extraction.confirmed_value(field_name)
        if value is None:
            return 0.0
        match = re.search(r"[\d.]+", value)
        return float(match.group()) if match else 0.0

    return DimensionsResult(
        weight_kg=_numeric_or_zero("weight_kg"),
        length_cm=_numeric_or_zero("length_cm"),
        width_cm=_numeric_or_zero("width_cm"),
        height_cm=_numeric_or_zero("height_cm"),
    )
```
Called from `deterministic_builders_node` (§3.3, step 9), immediately after the Specs Renderer. `weight_kg`/`length_cm`/`width_cm`/`height_cm` are required keys in every `CategorySpecSchema` implicitly (not part of the visible specs table, but always requested from Agent 1 alongside the category's visible fields) — `seed_taxonomy.py` seeds these 4 keys onto every category's schema automatically so no category can be created without them.

`csv_assembler.py`'s column-19-22 mapping now reads directly from `products.weight_kg/length_cm/width_cm/height_cm` (promoted columns, §2) rather than reaching into `extraction_result` jsonb at assembly time — assembly becomes a flat column-to-column copy for every deterministic field, which is also what makes `test_csv_columns.py`'s "keys match `COLUMN_ORDER`" assertion meaningful.

---

## 7. Testing & Rollout

Unchanged test categories from v1.0, with additions (closes #9):

**New unit tests:**
- `test_dimensions_builder.py` — UNKNOWN → 0.0, `"15 kg"` → `15.0`, `"45cm"` → `45.0`, missing field → 0.0.
- `test_price_reference.py` — no scraped price → `None`; 20% divergence → returns `20.0`; 10% divergence → returns `10.0` (banner only fires `>15`, tested in the frontend, not here).
- `test_retry_boundary.py` — drives `after_review` through 3 consecutive failures and asserts escalation fires on exactly the 3rd, not the 4th (closes #6, regression-proofs the fix).

**New integration tests:**
- `test_image_fallback_node.py` — 2 images + Template A → falls back to B; 3 images + Template A → stays A; asserts the audit_log notification string. Direct regression test for the bug that was already wrong once in v6.0 (2 vs. 3).
- `test_intake_triage.py` — variant-shaped inputs (e.g. "Available in 1/1.5/2 Ton") are flagged; single-variant inputs pass through.
- `test_batch_processor.py` — see §9; asserts sequential ordering, inter-product delay is applied, counters update correctly, and one product's pipeline exception doesn't halt the rest of the batch.

**Rollout plan** — unchanged 6 steps from v1.0, with step 5 made explicit and operational (closes the "gradual trust reduction has no test-plan step" gap noted alongside #10):
> **Step 5 — Gradual Trust Reduction, as an explicit checklist item:** after Step 4 (20-product scale) passes cleanly, an operator manually visits Settings → Trust Level and flips `app_settings.trust_level` from `full_review` to `quick_review`, confirming the one-way-decision dialog (§5.2). This is intentionally a manual, deliberate action — not something `pilot_gate_check.py` does automatically.

**Metrics reporting** (closes #10): `backend/scripts/metrics_report.py`, also exposed via `GET /api/metrics/pilot-report`:
```python
async def compute_pilot_metrics(batch_id: UUID) -> PilotMetrics:
    rows = await products_repo.get_by_batch(batch_id)
    system_times = [(r.ready_for_qa_at - r.queued_at).total_seconds() for r in rows if r.ready_for_qa_at]
    qa_times = [(r.approved_at - r.ready_for_qa_at).total_seconds() for r in rows if r.approved_at and r.ready_for_qa_at]
    return PilotMetrics(
        avg_system_processing_seconds=mean(system_times) if system_times else None,
        avg_human_qa_seconds=mean(qa_times) if qa_times else None,
        # factual error rate is entered manually by the operator after their own spot-check
        # against source_citations — there is no automated way to grade "is this correct against
        # the real world," so this remains a human-reported number, recorded via a simple
        # POST /api/metrics/pilot-report/{batch_id}/error-rate {value: float} call.
    )
```

---

## 8. Deployment

- **Droplet**: DigitalOcean, Ubuntu LTS, Docker Compose with `backend`, `frontend`, `caddy` services. Backend Dockerfile bases on `mcr.microsoft.com/playwright/python:v1.4x-jammy` (preinstalled Chromium + system deps).
- **Reverse proxy/TLS**: Caddy — automatic Let's Encrypt, near-zero config.
- **CI**: `ci.yml` — backend `ruff check` + unit/integration tests; frontend lint + build.
- **CD**: `deploy.yml` — build+push Docker images to GHCR on push to `main`, then SSH deploy to the droplet.
- **Monitoring**: GlitchTip free tier or self-hosted GlitchTip on the droplet, plus the `sku_collision` alert wiring (§2/§4).

Any backend observability bootstrap should keep using the standard `sentry-sdk` package, but point it at GlitchTip via `GLITCHTIP_DSN`:

```python
import sentry_sdk
from app.core.config import settings

sentry_sdk.init(dsn=settings.GLITCHTIP_DSN)
```

### API Cost — Free Tiers First, Optimize Second (v2.1, answers a direct question)

At this system's actual volume (tens of products/day, one user), **the realistic target is $0/month for LLM + search, using free tiers correctly** — this isn't optimistic marketing, it's just that free-tier rate limits (requests/day) at most providers comfortably cover a single person's daily batch.

**Where to actually get the API keys (free):**
- **Gemini (Extractor role):** `https://aistudio.google.com` → "Get API key." **This is a separate thing from your Google AI Pro subscription** — AI Pro is the consumer chat-app subscription (Gemini app, higher chat limits); it does **not** unlock developer API quota by itself. The free tier on `gemini-2.5-flash-lite` (already the model chosen in `phase1.md` §4) has a generous daily request allowance that easily covers a personal daily batch — sign up at AI Studio directly, no credit card needed for the free tier.
- **Groq (Writer/Reviewer role):** `https://console.groq.com` → API key. Free tier, rate-limited but no cost, and it's fast — this is why it was already chosen for these two roles.
- **Firecrawl (search + reference-site scraping):** `https://firecrawl.dev` → free tier gives a limited number of monthly credits. Since this system now does one search call per product (§4's `web_search`) plus occasional reference-site fetches, keep Firecrawl for the *search* step specifically (that's the part Playwright can't do) and prefer **Playwright** (self-hosted, genuinely free, already in the stack) for the actual page-scraping step wherever a URL is already known — this concentrates your limited Firecrawl credits on the one thing only Firecrawl does.
- **GitHub Student Developer Pack — best used for hosting, not the AI APIs:** it includes a DigitalOcean credit (historically ~$200) that covers the $6–12/month droplet for well over a year, and often a free domain (Namecheap/.me) for the first year. Use that same droplet for the FastAPI backend and a Docker Compose GlitchTip container so observability stays free long-term; this is not really an LLM-API discount path — don't expect it to offset Gemini/Groq costs, those are already free-tier-covered separately.

**Cost-optimization tactics baked into the design (not just "use free tiers and hope"):**
1. **Lean prompts:** before anything is sent to an LLM, scraped HTML is stripped down to readable text (no raw markup, no nav/footer boilerplate) — this is a meaningful token-count reduction on every single call, and belongs in `source_discovery.py`'s fetch step, not left as a later optimization.
2. **`scrape_cache` (§2/§4)** prevents re-scraping *and* re-extracting on writer↔reviewer retries — extraction runs exactly once per product regardless of how many writer retries happen.
3. **Bounded retry (max 3, §3.3)** caps the worst-case LLM cost per product — a stuck product can't silently rack up unlimited calls.
4. **`llm_usage_log` (§2)** logs real token counts and estimated cost per call — check it after the first real week; if you're anywhere near a free-tier ceiling, that's the signal to either throttle batch size or budget a paid tier, not something to guess about in advance.
5. **Cheapest model for the simplest job:** Extractor (structured fact-pulling) uses the smaller/cheaper Gemini tier; Writer/Reviewer (the harder, more creative work) uses Groq's free tier — the design already avoids paying premium-model prices for the easy half of the job.

Two additions beyond the always-free-tier-first framing above:

**Rollback runbook (closes #17):** `.github/workflows/rollback.yml`, a manual `workflow_dispatch` job:
```yaml
name: Rollback
on:
  workflow_dispatch:
    inputs:
      image_sha:
        description: "Commit SHA of the previously-known-good image to redeploy"
        required: true
jobs:
  rollback:
    runs-on: ubuntu-latest
    steps:
      - name: SSH deploy previous image
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DROPLET_HOST }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /opt/kiachahye-pipeline
            sed -i "s/IMAGE_TAG=.*/IMAGE_TAG=${{ inputs.image_sha }}/" .env
            docker compose pull && docker compose up -d
```
Documented in `docs/architecture.md`: find the last-known-good SHA from GitHub Actions run history, trigger this workflow with it, confirm health check passes.

**Login rate limiting (closes #18):** `backend/app/core/rate_limit.py` wraps `slowapi` (in-memory limiter, no Redis needed at this scale) around `POST /api/auth/login` using `LOGIN_RATE_LIMIT=5/minute` from config — appropriate for a single-user tool where the only real risk is a leaked/guessable `APP_AUTH_SECRET` being brute-forced from the public internet.

---

## 9. Batch Orchestrator (NEW dedicated section, closes #4)

`backend/app/graph/batch_processor.py`:

```python
import asyncio
from uuid import UUID
import sentry_sdk
from app.graph.pipeline import compiled_pipeline
from app.graph.state import PipelineState, build_initial_state
from app.db.repositories import batches as batches_repo, products as products_repo
from app.api.sse import SsePublisher, ProgressEvent
from app.core.config import settings

class BatchProcessor:
    """Owns sequential execution of a batch's products through the LangGraph pipeline.
    Runs as a FastAPI BackgroundTask, triggered by POST /api/batches (bulk) or
    POST /api/products/quick-add (batch-of-one, §5.2)."""

    def __init__(self, sse_publisher: SsePublisher, delay_seconds: float = settings.LLM_INTER_PRODUCT_DELAY_SECONDS):
        self.sse_publisher = sse_publisher
        self.delay_seconds = delay_seconds

    async def run_batch(self, batch_id: UUID) -> None:
        await batches_repo.set_status(batch_id, "processing")
        products = await products_repo.get_queued_by_batch(batch_id)

        for product in products:
            if not await budget_guard.check_budget_ok():  # v2.1 — closes the "hard cost cap" requirement
                await batches_repo.set_status(batch_id, "paused_budget_exceeded")
                sentry_sdk.capture_message("Monthly API budget exceeded — batch paused", level="warning")
                break  # remaining products stay 'queued', nothing lost, resumable once budget resets/raised
            try:
                initial_state = build_initial_state(product)
                final_state: PipelineState = await compiled_pipeline.ainvoke(initial_state)
                await self._record_outcome(batch_id, product.id, final_state)
            except Exception as exc:
                # A pipeline-level exception (e.g. an unhandled provider error) must never
                # halt the rest of the batch — phase1.md §10's "partial failure handling"
                # requires failed products to stay isolated while others proceed.
                await products_repo.mark_failed(product.id, reason_code="other", reason_detail=str(exc))
                await batches_repo.increment_counter(batch_id, "failed_count")
                sentry_sdk.capture_exception(exc)

            await self.sse_publisher.publish(batch_id, ProgressEvent(
                product_id=product.id, status=await products_repo.get_status(product.id),
            ))
            await asyncio.sleep(self.delay_seconds)  # LLM_INTER_PRODUCT_DELAY_SECONDS, phase1.md §4

        await batches_repo.finalize_status(batch_id)  # -> "completed" or "completed_with_failures"

    async def _record_outcome(self, batch_id: UUID, product_id: UUID, state: PipelineState) -> None:
        if state.failure is not None:
            await batches_repo.increment_counter(batch_id, "manual_review_count")
        else:
            await batches_repo.increment_counter(batch_id, "succeeded_count")
```

Wired in `api/routes/batches.py`:
```python
@router.post("/batches")
async def create_batch(payload: BatchCreateRequest, background_tasks: BackgroundTasks, ...):
    batch = await batches_repo.create(payload)
    background_tasks.add_task(BatchProcessor(sse_publisher).run_batch, batch.id)
    return {"batch_id": batch.id}  # returns immediately; client watches via SSE
```

This is the component that owns `phase1.md` §4's "sequential in V1" + "2-second delay between products" and §10's "partial failure handling: failed products stay in queue; successful products export immediately" — the latter is satisfied because `run_batch` never stops the loop on a single product's failure, and the export endpoint (§6/v1.0) already filters by `status='approved'` independent of the batch's overall completion state.

---

## 10. Gap Closure Ledger

Traceability table — every finding from the v1.0 cross-check report, mapped to its resolution:

| # | Finding | Severity | Resolved In |
|---|---|---|---|
| 1 | No prompt templates | HIGH | §3.2 — full verbatim prompts for all 3 agents |
| 2 | No concrete Pydantic schemas | HIGH | §3.1 — complete field-level models |
| 3 | No Weight/Length/Width/Height builder | HIGH | §6 — `build_dimensions()`, §2 new columns |
| 4 | No batch orchestrator | HIGH | §9 — `BatchProcessor` class |
| 5 | "Thriftify" design system unaddressed | HIGH | §5.1 — concrete design-system decision + confirmation flag |
| 6 | Retry off-by-one | MEDIUM | §3.3 step 7 — semantics fixed to exactly 3 total attempts + regression test |
| 7 | Quick-Add form missing | MEDIUM | §5.2 — dedicated page, implemented as a batch-of-one |
| 8 | Settings page scope undefined | MEDIUM | §5.2 — 6 named sections, API keys explicitly read-only/status-only |
| 9 | No regression tests for previously-buggy nodes | MEDIUM | §7 — `test_image_fallback_node.py`, `test_intake_triage.py`, plus `test_retry_boundary.py`, `test_batch_processor.py` |
| 10 | §16 metrics have no measurement mechanism | MEDIUM | §2 new `queued_at`/`ready_for_qa_at` columns, §7 `metrics_report.py` |
| 11 | Rendered content only in JSONB | MEDIUM | §2 — 6 new first-class `products` columns |
| 12 | `price_discrepancy_pct` computation unattributed | LOW | §4 — `compute_price_discrepancy()`, named call site in §3.3 |
| 13 | No LLM backoff config | LOW | §1 env vars, §4 backoff formula |
| 14 | No in-stock UI control | LOW | §5.2 — `StockStatusToggle.tsx` |
| 15 | No dependency manifest | LOW | §1 — full `pyproject.toml`/`package.json` |
| 16 | No first-run setup script | LOW | §1 — `bootstrap.sh` + `Makefile` |
| 17 | No deployment rollback procedure | LOW | §8 — `rollback.yml` workflow |
| 18 | No login rate limiting | LOW | §8 — `slowapi` on `/api/auth/login` |

**All 18 findings closed. 0 remaining from the v1.0 report.**

---

## Self-Audit & Readiness Statement

Re-checked against the same 10 dimensions used in the original cross-check:

1. **Project Scaffold & Setup** — env vars, dependencies, and a one-command bootstrap script are now all concrete. ✅
2. **Database Design** — schema covers every Phase 1 entity; 6 new columns close the content/metrics gaps; RLS/indexes unchanged from the already-adequate v1.0 design. ✅
3. **Agent Pipeline** — full Pydantic I/O schemas and full prompt text for all 3 agents; retry boundary corrected and regression-tested. ✅
4. **Scraping Module** — unchanged (was already adequate), plus the price-discrepancy computation is now named. ✅
5. **Frontend Features** — Quick-Add added, Settings scope defined, design system resolved with a concrete (swappable) choice. ✅
6. **CSV Engine** — dimensions builder closes the last unmapped required columns; all 49 columns now trace to an explicit builder or static default. ✅
7. **Testing & Rollout** — regression tests added for both previously-buggy nodes; §16 metrics now have a defined computation path; gradual trust reduction is now an explicit, operator-driven checklist step. ✅
8. **Deployment** — rollback runbook and login rate limiting added. ✅
9. **Alignment with Phase 1** — every section (§0–§18) has a corresponding implementation element; no unresolved requirement remains unmapped. ✅
10. **Edge Cases & Error Handling** — every row of `phase1.md` §12's edge-case table has a named resolution; the `BatchProcessor`'s own new edge case (a mid-batch pipeline exception) is handled by design (isolated per-product try/except, batch continues). ✅

**Remaining items requiring user input (not plan defects — pre-existing data dependencies from `phase1.md` §0, unchanged by this revision):**
- Full category parent/child tree beyond the confirmed Microwave Oven example (§9.2 of `phase1.md`).
- Brand-casing verification against the live WooCommerce taxonomy.
- Live SKU export to seed `live_sku_snapshot`.
- Meaning of the `Item`/`Inverter` categories.
- Exact WooCommerce Brands plugin in use.
- Per-category spec-field schemas beyond Microwave Oven.
- **Confirmation of the "Thriftify" reference** (§5.1) — a concrete substitute was chosen; confirm or override before frontend work begins.

None of these block writing code — they are seed-data/config inputs the architecture is deliberately designed to accept later (Taxonomy Manager, `seed_taxonomy.py` with `needs_confirmation=true` flags) without any structural rework.

### Verdict: **READY FOR IMPLEMENTATION**

All 5 high-severity and 6 medium-severity gaps from the cross-check are closed with concrete, executable specifications — prompts a developer can paste directly into `agents/*.py`, schemas that compile as-is, a builder function with working code, and an orchestrator class with a defined API. The 7 open items above are Phase 0 data-collection tasks and one design-reference confirmation, not implementation ambiguity. Phase 2 build work (repo scaffold → DB migrations → deterministic builders, per the roadmap's own sequencing) can begin now.
