# Phase 3: Testing & Hardening Plan

**Status:** Planning document only — no test code has been written yet. This locks the test strategy the same way `phase1.md` locked the spec and `phase2.md` locked the architecture, before any of it is built.
**Builds on:** `phase1.md` (v7.0, locked spec — esp. §15 rollout plan, §16 success metrics, §12 edge cases) and `phase2.md` (v2.0, locked architecture — esp. §3 agent pipeline, §7 test scaffolding, §9 batch orchestrator).
**Purpose:** answer one question with total precision — *exactly* what gets verified, in what order, with what pass/fail threshold, before a single real product is allowed to touch the live kiachahye.pk catalog.
**Relationship to the roadmap in `phase2.md`:** this document is the detailed execution plan for what that roadmap calls Phase 5 ("Pilot & Hardening"), written in full now so nothing is improvised once Phase 3 (pipeline) and Phase 4 (frontend) are actually built.

---

## 1. Testing Pyramid Overview

```
                    ┌─────────────────────────┐
                    │   6. LIVE ROLLOUT        │  real inventory, quick review mode
                    ├─────────────────────────┤
                    │   5. SCALE-UP GATE (20)  │  pilot criteria re-run at 20 products
                    ├─────────────────────────┤
                    │   4. PILOT GATE (5)      │  phase1.md §15 step 2 acceptance criteria
                    ├─────────────────────────┤
                    │   3. STAGING IMPORT      │  real WooCommerce staging site
                    ├─────────────────────────┤
                    │   2. E2E (1 product)     │  real scrape + real LLM, no import
                    ├─────────────────────────┤
                    │   1. INTEGRATION (mocked)│  FakeLLMClient + FakeScraper, CI-run
                    ├─────────────────────────┤
                    │   0. UNIT (no I/O)       │  deterministic builders, CI-run
                    └─────────────────────────┘
```

Each layer only starts once the layer below it passes. No layer is ever skipped, including for a "quick fix" — a regression at layer 0 that isn't caught before layer 3 is exactly the failure mode this whole project exists to eliminate.

---

## 2. Layer 0 — Unit Tests (no I/O, run on every commit)

All in `backend/tests/unit/`, pure functions, no network/DB/LLM calls, must complete in under 5 seconds total in CI.

| Test file | Concrete cases |
|---|---|
| `test_name_builder.py` | `build_name("TCL","1 Ton","12 SVN-AI-CO-31G/S","Inverter Split Air Conditioner")` → abbreviates to `"...Inverter Split AC"`, result ≤44 chars. `"1.0 Ton"` input → `"1 Ton"` in output. `"20 Liters"` → `"20L"`. Name that's already ≤44 chars is returned unmodified (no needless abbreviation). |
| `test_tag_generator.py` | `("DAWLANCE","Microwave Oven")` → exactly `"DAWLANCE, Microwave Oven, HW"`. Casing is never altered even if input brand differs in case from stored taxonomy (function trusts caller to pass the exact stored string — this is asserted, not silently "fixed"). Output always has exactly 2 commas. |
| `test_specs_renderer.py` | Row count == `len(schema.fields) + 1` (the +1 is the Warranty row). Warranty row is always last, always `font-weight: bold`. Category with no `category_spec_schemas` row raises `MissingSchemaError`, never renders a partial/empty table. |
| `test_dimensions_builder.py` | `confirmed_value("weight_kg")=="15"` → `15.0`. `confirmed_value(...)==None` (UNKNOWN or missing) → `0.0`. `"45cm"` → `45.0` (unit suffix stripped). Malformed string (`"heavy"`) → `0.0`, never raises. |
| `test_price_reference.py` | `scraped=None` → `None` (nothing to compare). `scraped=41300, entered=41300` → `0.0`. `scraped=41300, entered=35000` → `~15.26`. `scraped=0` → `None` (avoid div-by-zero). |
| `test_csv_columns.py` | `len(COLUMN_ORDER) == 49`. Order matches `phase1.md` §8.7 transcribed **verbatim** in the test body (column-by-column, not just a count check — this is the test that would have caught the v6.0→v7.0 `Categories` hierarchy bug if it existed at the column-order level). |
| `test_html_sanitizer.py` | `sanitize('It\'s a "great" product')` → entities escaped, original string in `products.writer_result` untouched. Idempotent: sanitizing an already-sanitized string doesn't double-escape. |
| `test_sku_guard.py` | SKU present in `live_sku_snapshot` → collision detected, returns the live `wc_product_id`. SKU absent → no collision. **`live_sku_last_synced_at` is null → guard raises `SnapshotNotSyncedError`, never silently treats empty as "no collisions"** (this is the single most safety-critical unit test in the whole suite — a false negative here overwrites a live product). |
| `test_taxonomy_lock.py` | Exact-match brand/category → resolves. Near-miss casing (`"dawlance"` vs stored `"DAWLANCE"`) → `TaxonomyMismatchError`, never fuzzy-matched. `needs_confirmation=true` category → `TaxonomyMismatchError` even if the name matches exactly. Produces `"Home Appliance > Microwave Oven"` string format exactly. |
| `test_retry_boundary.py` | Simulates 3 consecutive `ReviewResult(passed=False)` — asserts escalation fires on exactly the 3rd failed review (not the 2nd, not the 4th), with `reason_code` correctly split between `preflight_score_low` (score <90) and `writer_reviewer_exhausted` (score ≥90 but another check failed). |

**Layer 0 exit criterion:** 100% pass, 100% of the above concrete cases present and green, before any integration test is run.

---

## 3. Layer 1 — Integration Tests (mocked LLM + mocked scraper, run on every commit)

All in `backend/tests/integration/`, using `FakeLLMClient` (returns canned Pydantic-model-shaped responses per test case, no network) and `FakeScraper` (returns canned `ScrapeResult` objects). CI budget: under 60 seconds total.

| Test file | Concrete scenarios |
|---|---|
| `test_extractor_node.py` | Required field absent from all fake source text → citation with `value="UNKNOWN"`, `confidence="unreachable"`. Two fake sources disagree on `capacity` → two citations recorded with `confidence="confirmed"` each, `ExtractionResult.has_conflict("capacity")==True`. All sources return `status="blocked"` → every field ends up `UNKNOWN`, `after_extractor` routes to escalation with `reason_code="source_unreachable"`. |
| `test_writer_node.py` | `FakeLLMClient` returns malformed JSON (missing a required key) → Pydantic validation raises inside the node → caught as a *writer* failure → routes to retry, **never** to `escalation_handler` directly (this is the test that guards the extraction-vs-writer failure-type split from `phase1.md` §3/§5.6). `FakeLLMClient` returns exactly 4 FAQs → `WriterOutput` validator rejects it before it ever reaches the Reviewer. |
| `test_reviewer_node.py` | Warranty string differs by one character across the 4 injection points → `warranty_consistent=False`, `passed=False`, **regardless of `preflight_score`** (this must be tested with a deliberately high fake score to prove the warranty check is a hard gate, not a weighted contributor). `preflight_score=85` → `passed=False`, routes to retry. `retry_count==3` on the 3rd failure → routes to `escalation_handler` with `writer_reviewer_exhausted`. |
| `test_graph_routing.py` | Every edge declared in `graph/pipeline.py` is exercised at least once across the test suite (a coverage assertion over the compiled graph's edge list, not just node-level tests — catches an edge that was defined but never reachable). |
| `test_image_fallback_node.py` | 2 fake image URLs + `template_choice="A"` → state flips to `"B"`, an `audit_log` row is asserted with the exact notification text from `phase1.md` §7.3. 3 images + `"A"` → stays `"A"`. |
| `test_intake_triage.py` | Raw input title containing `"1/1.5/2 Ton"` or similar multi-value patterns → `variant_shaped=True`, routes straight to escalation, **never** reaches `extractor_node` (assert the fake scraper was never called). Single-value title → passes through untouched. |
| `test_batch_processor.py` | 3-product batch where product 2's pipeline call raises an exception → products 1 and 3 still complete normally, `batches.failed_count==1`, `succeeded_count`/`manual_review_count` reflect the other two correctly. Asserts `asyncio.sleep` is called with exactly `LLM_INTER_PRODUCT_DELAY_SECONDS` between each product (mocked clock, not a real 2-second wait in CI). |

**Layer 1 exit criterion:** 100% pass. This is the last layer that runs in every CI pipeline run (every push/PR per `phase2.md` §8's `ci.yml`) — Layers 2+ are manual/pre-pilot only.

---

## 4. Layer 2 — End-to-End Test (1 real product, real scrape + real LLM, no import)

Run manually, once, before the pilot begins. Marked `@pytest.mark.e2e`, excluded from CI.

**Test product:** the confirmed real example — Dawlance/Homage-class microwave, e.g. the verified `Homage 20L HDG-201S Grill Microwave` (`phase1.md` §6.1) or the real `Dawlance 30L DW-131 HP Sync Microwave` sample the user provided. **Microwave Oven only** — it's the one category with a confirmed `category_spec_schemas` row (`phase1.md` §7.7); no other category schema is verified yet, so no other category can meaningfully pass this test.

**Procedure:**
1. Submit via Quick-Add (`phase2.md` §5.2) with real SKU, real price, `template_choice="A"`.
2. Let it run through the full pipeline with real Playwright/Firecrawl scraping and real Gemini/Groq calls (no mocks).
3. Assert: `products.status == "ready_for_qa"`, `csv_row` has all 49 keys, `csv.DictReader` round-trips the assembled CSV row cleanly (no column-count drift).
4. Assert every `source_citations` row has a non-null `source_url` where `confidence == "confirmed"`, and `value == "UNKNOWN"` everywhere `confidence == "unreachable"` — this is the live proof that the no-hallucination contract holds against a real LLM, not just the fake one.
5. Manually read the generated `short_description`/`description`/FAQ text and confirm every factual claim traces to a real citation — this is a human doing exactly what `test_reviewer_node.py`'s fact-cross-check automates, as a sanity check that the automation itself isn't fooling itself.

**Exit criterion:** all 5 assertions pass on this single product. If it fails, fix and re-run — do not proceed to Layer 3 on a failing E2E run.

---

## 5. Layer 3 — Staging Import Validation

**Precondition check (do this first, it's a hard blocker):** confirm a WooCommerce staging environment exists. If it does not, the fallback is importing directly to production **as Draft** (`Published=-1`) — never test against a live/published state under any circumstance.

`backend/scripts/staging_import_checklist.md`, run once per pilot batch:

1. Export the batch's approved products via `POST /api/batches/{id}/export` (`phase2.md` §6).
2. Import the CSV via WooCommerce's own CSV Importer (Products → Import) — this is intentionally the exact same import path the user uses manually today, so any format incompatibility surfaces here, not in front of live customers.
3. **Per imported product, verify:**
   - Product page renders with no visual breakage (specs table, FAQ blocks, image placeholders don't collapse the layout).
   - `Categories` resolved to the correct nested term (`Home Appliance > Microwave Oven`), not a new flat/duplicate term — check Products → Categories for an accidental duplicate.
   - `Brands` resolved to the existing taxonomy term, not a new duplicate (same check as above for the Brands taxonomy).
   - `Tags` shows exactly 3 tags, correct casing.
   - Open the product in the editor and **save it once** — then check the Rank Math score shown in wp-admin. Per `phase1.md` §6.7, the CSV's raw `Meta: rank_math_seo_score` value is cosmetic; this manual re-save is the only way to get Rank Math's real score. Record the real post-save score per product.
   - Run the product URL through Google's Rich Results Test (or equivalent) — confirm the JSON-LD Product schema resolves price, availability, and brand correctly (`phase1.md` §6.5 — "don't assume it's correct just because the plugin claims to auto-generate it").
   - Confirm `Published` status is `Draft` — this product must **not** be publicly visible yet.
4. Record pass/fail per product in a simple table (product SKU → each check above → pass/fail).

**Exit criterion:** every check passes for every product in the batch. Any failure routes that specific product back to Manual Review (even though it already passed the automated pipeline) and blocks that product — **not the whole batch** — from advancing.

---

## 6. Layer 4 — Pilot Gate (5 products)

This operationalizes `phase1.md` §15 step 2 exactly.

**Product selection constraint (important, not stated explicitly in `phase1.md` but a direct consequence of `phase2.md` §3.1):** all 5 pilot products **must** be Microwave Oven category — the only category with a confirmed `category_spec_schemas` row. Picking a product from an unconfirmed category (e.g. Air Conditioner) would test against a schema that was never verified against real data, contaminating the pilot's results. If fewer than 5 real microwave products are available in the current raw input list, wait for more or pull from historical model numbers already known — do not substitute an unverified category just to hit the number 5.

**Acceptance criteria (verbatim from `phase1.md` §15, operationalized as code in `pilot_gate_check.py`):**

```python
async def pilot_gate_check(batch_id: UUID) -> PilotGateResult:
    products = await products_repo.get_by_batch(batch_id)
    assert len(products) == 5, "Pilot gate requires exactly 5 products"

    failures = []
    for p in products:
        if p.preflight_score < 90:
            failures.append(f"{p.sku}: preflight_score={p.preflight_score} (<90)")
        if not _warranty_consistent(p):
            failures.append(f"{p.sku}: warranty mismatch across the 4 injection points")
        # CSV-assembly errors are read from audit_log, not re-derived
        csv_errors = await audit_repo.count_events(product_id=p.id, event_type="csv_assembly_error")
        if csv_errors > 0:
            failures.append(f"{p.sku}: {csv_errors} CSV assembly error(s) logged")

    # Factual correctness is the one criterion that cannot be automated — it requires
    # the user's own manual re-check against real-world sources, recorded via:
    # POST /api/metrics/pilot-report/{batch_id}/error-rate {value: 0.0}
    manual_error_rate = await metrics_repo.get_reported_error_rate(batch_id)
    if manual_error_rate is None:
        failures.append("Manual factual re-check not yet recorded — cannot pass gate without it")
    elif manual_error_rate > 0:
        failures.append(f"Manual re-check found {manual_error_rate}% factual error rate (must be 0% for pilot)")

    return PilotGateResult(passed=len(failures) == 0, failures=failures)
```

**Exit criterion:** `pilot_gate_check.py` returns `passed=True` — 5/5 products, preflight ≥90, 0 CSV errors, warranty consistent, **and** the user's own manual factual re-check reports 0% error rate. Any single failure blocks advancing to Layer 5; fix the root cause (not just the symptom) and re-run the pilot batch from Layer 2 if the failure suggests a pipeline defect, or from Layer 4 alone if it was a one-off data issue.

---

## 7. Layer 5 — Scale-Up Gate (20 products)

Re-runs the exact same `pilot_gate_check.py` logic against a 20-product batch (the script already parameterizes on `batch_id`, no code change needed — this re-use is why the gate was written as a script and not a one-off manual checklist).

**Category scope:** still Microwave Oven only, **unless** `phase1.md` §0 items for another category (its spec-field schema, confirmed via Taxonomy Manager) have been completed in the meantime. Expanding category scope and scaling batch size are two independent decisions — don't do both in the same batch. If a new category's schema was just confirmed, run *its own* separate 5-product pilot (Layer 4) before folding it into a combined scale-up batch.

**Exit criterion:** same as Layer 4, but the error-rate tolerance is now `< 1%` (per `phase1.md` §16's success metric, not 0%) since 20 products makes a single edge-case miss statistically expected rather than disqualifying — but **any** SKU-collision or warranty-mismatch failure at this stage is still a hard stop regardless of overall percentage, since those are safety-critical, not statistical, failure modes.

---

## 8. Gradual Trust Reduction (operational, not automated)

Per `phase2.md` §5.2/§7: after Layer 5 passes cleanly, an operator manually visits Settings → Trust Level and flips `app_settings.trust_level` from `full_review` to `quick_review`, confirming the one-way-decision dialog. **This document adds one explicit rule:** the flip happens only after Layer 5's `manual_error_rate` has been at 0% for at least 2 consecutive scale-up batches, not just 1 — a single clean 20-product run could be luck; two in a row is a pattern. Record both batch IDs in the sign-off checklist (§10).

---

## 9. Security & Safety Hardening Checklist (pre-live, one-time)

Run once, before the very first real (non-pilot) batch, independent of the pilot gates above:

- [ ] **RLS verification:** connect to Supabase using the `anon` key (not `service_role`) and confirm every table returns zero rows / permission denied. This is the concrete test for `phase2.md` §2's "add no permissive policies" claim — don't just trust the migration file, query it.
- [ ] **SKU-guard live-fire test:** intentionally submit a product with a SKU known to exist in `live_sku_snapshot`, confirm it's blocked at export with `reason_code="sku_collision"` **and** that a GlitchTip alert actually fires (per `phase2.md` §8's explicit alert wiring) — trigger it once for real, don't just trust the code review.
- [ ] **Snapshot-staleness guard test:** confirm that if `live_sku_last_synced_at` has never been set, CSV export is hard-blocked (this is `test_sku_guard.py`'s most important case, §2 above — re-verify it against the real deployed environment, not just the unit test).
- [ ] **Login rate limiting:** confirm 6 rapid failed login attempts against the deployed `/api/auth/login` actually get throttled (`phase2.md` §8, `LOGIN_RATE_LIMIT=5/minute`).
- [ ] **Secrets audit:** confirm no API key appears in `git log`, in any committed file, or in the frontend's built JS bundle (grep the built `frontend/.next` output for the literal key strings as a final check).
- [ ] **Backup/restore test:** trigger a Supabase point-in-time restore (or manual pg_dump/restore) in a scratch project, confirm the schema and seed data come back intact — do this before there's real production data to lose, not after.
- [ ] **Draft-only guarantee:** manually attempt to override `Published` away from `-1` anywhere in the codebase (grep for the literal value) — confirm there is exactly one place it's set, and it's always `-1` for V1, with no code path that could publish a product automatically.

---

## 10. Final Sign-Off Checklist (before "process real inventory" is flipped on)

A single checklist, filled in by the user before treating the system as production for their actual daily work:

| Item | Status | Evidence |
|---|---|---|
| Layer 0 unit tests | ☐ pass | CI run link |
| Layer 1 integration tests | ☐ pass | CI run link |
| Layer 2 E2E (1 product) | ☐ pass | product SKU + assertion results |
| Layer 3 staging import | ☐ pass | per-product check table (§5) |
| Layer 4 pilot gate (5 products) | ☐ pass | `pilot_gate_check.py` output |
| Layer 5 scale-up gate (20 products) ×2 consecutive clean runs | ☐ pass | both batch IDs |
| Security & safety hardening checklist (§9) | ☐ all items checked | |
| `phase1.md` §0 checklist fully resolved for every category being processed | ☐ done | |
| Trust level flipped to Quick Review (§8) — optional, user's choice | ☐ done / ☐ staying in Full Review |

**Only once every row above is checked does a batch's CSV get imported against the real, live kiachahye.pk catalog outside of Draft-safety-net testing conditions.**

---

## Self-Check

- **Traces to `phase1.md`:** every acceptance number (5 products, 20 products, ≥90 preflight, 100%/<1% error rate, 0% at pilot) is pulled directly from `phase1.md` §15/§16, not invented here.
- **Traces to `phase2.md`:** every test file name matches the ones already scaffolded in `phase2.md` §1/§7; this document adds concrete cases, not new file paths.
- **New rule introduced here, flagged explicitly:** the "Microwave Oven only" pilot constraint isn't stated verbatim in either prior document — it's a direct logical consequence of `phase2.md` §3.1 (only one category has a confirmed spec schema) that would otherwise go unnoticed until someone tried to pilot an Air Conditioner and got inconsistent results. Confirm this constraint is acceptable before the pilot begins.
- **Open dependency, unchanged from prior documents:** all of this still assumes the `phase1.md` §0 checklist items are resolved for whichever category is being tested — this document doesn't remove that dependency, it makes explicit where in the test sequence it would first bite (Layer 4, if an unconfirmed category were used).

**Verdict: Ready to execute once Phase 3 (pipeline) and Phase 4 (frontend) from `phase2.md`'s roadmap are actually built** — this document defines *how* to validate them, not a replacement for building them first.
