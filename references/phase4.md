# Phase 4: Live Integration & Deployment Plan

**Status:** Planning document only. Written now, same as `phase1.md`/`phase2.md`/`phase3.md`, before the pipeline/frontend are actually built and before Phase 3's tests have actually been run against real code. Everything below describes what happens *once* Phase 3's gates (`phase3.md` §10 sign-off checklist) are genuinely all checked — not a claim that they already are.
**Builds on:** `phase1.md` (v7.0, locked spec), `phase2.md` (v2.0, locked architecture), `phase3.md` (locked test/hardening plan).

**Two corrections to the brief before the plan starts, because building around a wrong assumption here would undo Phase 1–3's safety work:**

1. **This system has no WooCommerce REST API integration, and shouldn't get one for V1.** The entire safety model in `phase1.md`/`phase2.md` rests on: the system produces a CSV → a human manually imports it through wp-admin's own CSV Importer → every row lands as Draft (`Published=-1`). That manual import step *is* the safeguard against silently pushing bad data live. "Environment setup" below is about syncing taxonomy/SKU reference data into *our own* database, and re-verifying the CSV format against the real site — not generating WooCommerce API keys. If automated publishing is ever wanted later, that's a deliberate, separate architecture decision for a future phase, not something to fold in here.
2. **A `/health` endpoint didn't exist in `phase2.md` until now.** Post-deployment monitoring (§5) needs one; it's been added there (`backend/app/api/routes/health.py`, `GET /health`, no auth) so this document doesn't introduce an undocumented dependency.
3. **GlitchTip is the observability target for V1.** Keep the standard `sentry-sdk` package in the backend, but point its DSN at `GLITCHTIP_DSN`, either on the same DigitalOcean droplet via Docker Compose or on GlitchTip's free SaaS tier.

---

## 1. Environment Setup — Connecting to the Real Live Site

### 1.1 What "connecting" actually means here

There is no API key exchange with WooCommerce. The only things that need to happen:
- Real taxonomy/SKU data gets pulled out of the live site (as file exports, done manually in wp-admin — read-only, zero risk) and loaded into *our* Supabase tables.
- The CSV column mapping gets re-verified against a **fresh** real export, in case a plugin update changed anything since `phase1.md` v7.0 was written.
- The manual CSV-import path is rehearsed once against real (but Draft) data before it's used for daily work.

### 1.2 Steps

1. **Live one-time check right before go-live** (most of this should already be done progressively via the Taxonomy Manager during Phase 2/3 — this is a final glance, not a fresh audit):
   - Export one current real product as an actual `.csv` file from wp-admin → Products → Export. Diff its headers against `phase2.md` §6's `COLUMN_ORDER`. If anything differs, that's a stop-the-line issue — fix the column mapping before touching anything else.
   - Confirm the exact Brands plugin in use (only needed once, doesn't change often).
   - `Item`'s meaning, if still unresolved, and any category still `needs_confirmation=true` — resolve directly in the Taxonomy Manager, not via a separate export. (`Inverter` is already confirmed real, nothing to do there.)
   - Deploy the GlitchTip container stack once on the same DigitalOcean droplet as the backend/frontend using Docker Compose, then point `GLITCHTIP_DSN` at that instance (or the free GlitchTip SaaS tier if you prefer not to self-host).
2. **If you haven't already been doing it live in the UI:**
   - Taxonomy Manager (`phase2.md` §5.2) — set `parent_id` for any category still unconfirmed, flip `needs_confirmation=false` as you go.
   - Same screen — flip `casing_confirmed=true` per brand as you confirm each one against the real site.
   - Settings → Live SKU Snapshot (`phase2.md` §5.2) → upload the full SKU CSV. Confirm `live_sku_last_synced_at` updates to "now."
3. **Re-verify the CSV mapping** using the fresh export from step 1 — this is `phase2.md` §7's `test_csv_columns.py` assertion, but run once by eye against real current data, not just the historical sample from when v7.0 was written.
4. **Rehearsal import:** if a WooCommerce staging clone exists, do one full rehearsal import there using this fresh real data. If no staging clone exists, the rehearsal happens directly on production, strictly as Draft — confirmed by the checklist item below.
5. **Confirm the Draft-only guarantee one more time**, live: after import, check the product list in wp-admin and confirm the new items show status "Draft," not "Published," not visible on the public site.

### ✅ Section 1 Checklist
- [ ] Fresh product CSV exported and diffed against `COLUMN_ORDER` — no mismatch
- [ ] Full category tree loaded, all categories used so far have `needs_confirmation=false`
- [ ] Brand casing confirmed for all brands used so far
- [ ] Live SKU snapshot uploaded, `live_sku_last_synced_at` is current
- [ ] `Item`/`Inverter` category meaning resolved (kept or deleted)
- [ ] Rehearsal import completed (staging or Draft-on-production) with no column errors
- [ ] Confirmed imported items show as Draft, not visible publicly

---

## 2. First Real Batch Execution

### 2.1 Scope of the first batch

10–20 real products, picked by you. **One constraint carried over from `phase3.md` §6:** stick to categories that already have a confirmed `category_spec_schemas` row (Microwave Oven, plus any category you've since built out a spec schema for). Don't pick a category whose spec-field list has never been defined — that's an untested code path, not a "real batch," and it belongs in its own mini-pilot first.

### 2.2 Safety gates for this specific batch

- **Dry-run = the existing QA Panel, nothing new to build.** Every batch already stops at `status='ready_for_qa'` before anything is exportable (`phase2.md` §3.3) — there's no separate "preview mode" to add; that gate already exists by design.
- **Force Full Review Mode for this batch specifically, regardless of the current `trust_level` setting.** Even if Quick Review Mode was earned during the Phase 3 pilot, the first batch against *real* production data is a new context — review every field, with source citations, on every product in this batch. Only fall back to whatever `trust_level` is set to starting with the *second* real batch.
- **Export Approved Only stays in force** (`phase2.md` §6) — anything not explicitly approved in the QA Panel never reaches the CSV.

### 2.3 Import steps

1. Export the approved batch (`POST /api/batches/{id}/export`).
2. In wp-admin → Products → Import, upload the CSV.
3. On the column-mapping screen, **visually confirm every column auto-mapped correctly** before clicking through — a plugin update changing an expected header name would show up here as an unmapped column, not as a silent failure.
4. Run the import.
5. Post-import checks, per product (same as `phase3.md` §5's staging checklist, now against real Draft products):
   - Page renders correctly, specs table and FAQ display properly.
   - No literal `[square-bracket]` text anywhere in the description/specs that WordPress could misparse as a shortcode — a corner case not covered earlier; spot-check it here.
   - Category resolved to the correct existing nested term — **not** a new duplicate category.
   - Brand resolved to the correct existing term — **not** a new duplicate brand.
   - Exactly 3 tags, correct casing.
   - Open and save once in the editor, note the real (post-save) Rank Math score.
   - Confirm status is still Draft.

### 2.4 Rollback procedure

Because every import lands as Draft, "rollback" is low-stakes by construction — nothing was ever visible to a customer. If something's wrong:
1. Find the imported product IDs from `csv_exports.product_ids` for that batch.
2. In wp-admin, select those products and move them to Trash (bulk action).
3. Fix whatever caused the issue (taxonomy mapping, a category's spec schema, a template) back in the system.
4. Re-run the batch from the QA Panel (or from scratch if the root cause was upstream in extraction).

### ✅ Section 2 Checklist
- [ ] First real batch limited to categories with a confirmed spec schema
- [ ] Full Review Mode used for every product in this batch, regardless of saved trust level
- [ ] Column-mapping screen visually confirmed during import
- [ ] Post-import checks completed per product
- [ ] Rollback procedure understood and tested at least once (even on a deliberately-broken practice product) before relying on it for real

---

## 3. Daily Workflow & Operations Manual

**Note on "screenshots/mockups":** none are included here — the frontend doesn't exist yet, so a screenshot would be fictional. Every step below instead references the exact page name from `phase2.md`'s page tree; take real screenshots once the UI is built and slot them in.

### 3.1 Daily steps (plain language)

1. Receive the raw product list (model numbers + short titles) as usual.
2. Open the dashboard, log in.
3. For a batch of several products: **Batches → New Batch**, paste or upload the raw list, fill in SKU/price/stock for each. For a single urgent product: **Products → Quick-Add** instead.
4. Submit. Watch the **live progress view** on the batch page — no need to sit and wait, it updates itself.
5. Once products reach "Ready for QA," open the **Human QA Panel** for each. Depending on the current review mode:
   - *Full Review*: check every field, click through each source citation to verify it's a real, correct source.
   - *Quick Review* (only after trust is established, `phase3.md` §8): check just the flagged fields.
6. Approve the correct ones. Anything that looks wrong: reject it, or fix the specific field if the UI allows an inline correction, or leave it — it'll route to Manual Review if the system itself already flagged it.
7. Check the **Manual Review Queue** for anything that got auto-flagged (source unreachable, spec conflict, SKU collision, etc.) — each item shows *why* it's there. Resolve what you can (e.g., the site was just slow — retry), leave the rest for a developer to look at.
8. Once you're happy with the approved list: **Export CSV** from the batch page.
9. Import that CSV into WooCommerce the normal way (Products → Import), same as always.
10. Products land as Draft — do your final visual check, then publish them yourself whenever you're ready (publishing itself stays a manual, deliberate action, same as it's always been).

### 3.2 Regular maintenance (not daily)

| Task | Frequency | Where |
|---|---|---|
| Warranty Matrix re-audit | Quarterly | Settings → Warranty Matrix (flags entries older than 90 days) |
| Live SKU snapshot refresh | Before each batch, or weekly at minimum | Settings → Live SKU Snapshot |
| Brand source URL updates | Whenever a brand redesigns their site | Settings → Brand Source URLs |
| New category spec schema | Whenever you start selling a new appliance category | Taxonomy Manager |

### ✅ Section 3 Checklist
- [ ] Daily workflow steps followed once, start to finish, without developer help
- [ ] Maintenance schedule understood and a reminder set (calendar/quarterly) for the warranty re-audit

---

## 4. User Training & Handover

**Adaptation note:** since the operator and the system's builder are the same person in this project, "training" here means a structured first real run-through, not an onboarding of a separate employee — but written so it also works if someone else ever takes over this role.

### 4.1 Suggested 2-hour session agenda

| Time | Topic |
|---|---|
| 15 min | Login, dashboard tour, where everything lives |
| 20 min | Create a batch (paste a real small list), watch it process |
| 15 min | Quick-Add walkthrough (one single urgent product) |
| 30 min | Human QA Panel — Full Review Mode, what a source citation means, how to spot a wrong fact |
| 15 min | Manual Review Queue — what each failure reason means, what to do about each one |
| 15 min | Export → import into WooCommerce → post-import checks |
| 10 min | Settings tour (Warranty Matrix, Brand URLs, SKU snapshot, Trust Level) |

### 4.2 Troubleshooting Cheat Sheet

| Symptom | Likely cause | What to do |
|---|---|---|
| Can't log in | `APP_AUTH_SECRET` mismatch | Check the `.env` value matches what you're typing |
| Product stuck in Manual Review | Check the `reason_detail` shown on the item | Source unreachable → retry later; spec conflict → resolve manually; SKU collision → check if it's a real duplicate or a stale snapshot (refresh it) |
| A batch seems to have stalled | Backend or a scrape target is down | Check the batch's progress view; check `/health`; check GlitchTip |
| CSV import fails in WooCommerce | Column mismatch after a plugin update | Re-run the §1 mapping diff against a fresh export |
| A product's specs look wrong despite passing review | A source cited a wrong fact from a bad webpage | Reject it, note it in the feedback log (§5.2), it feeds back into schema/prompt tuning |
| Who do I contact for anything beyond this table? | — | The system's builder (you) — log the issue in `docs/pilot_feedback.md` (§5.2) either way, so nothing gets lost |

### ✅ Section 4 Checklist
- [ ] Training session completed
- [ ] Troubleshooting sheet kept somewhere easy to find (printed or pinned)

---

## 5. Post-Deployment Monitoring

### 5.1 Uptime monitoring

Add `GET /health` (no auth, returns `{"status":"ok"}` if the DB connection is alive — `backend/app/api/routes/health.py`, noted back in `phase2.md` §1). Point a free UptimeRobot (or similar) monitor at `https://<your-domain>/health`, checked every 5 minutes, alerting by email/SMS on downtime. Route backend error events to GlitchTip via `GLITCHTIP_DSN` so alerts surface in the same observability flow as the dashboard.

### 5.2 Feedback loop

Given single-user scale, don't build a new database table for this — it's overkill. Keep `docs/pilot_feedback.md`, one line per issue: date, product SKU, what was wrong, whether it was caught before or after CSV export. Review this file at the 1-week checkpoint (§5.3) and feed anything recurring back into the relevant prompt (`phase2.md` §3.2) or category spec schema (`phase2.md` §3.1).

### 5.3 One-week follow-up review

Run `metrics_report.py` / `GET /api/metrics/pilot-report` (`phase2.md` §7) against the first week's real batches. Compare against `phase1.md` §16 targets:

| Metric | Target | This week's actual |
|---|---|---|
| System processing time / product | (measured, no fixed target) | — |
| Human QA time / product | < 5 min | — |
| Factual error rate | < 1% | — |
| Rank Math score (post-save) | 95+ | — |
| Warranty consistency | 100% | — |

Use this table plus `docs/pilot_feedback.md` to decide: stay in Full Review a while longer, move to Quick Review, or hold off on Phase 5 (V2 features) until specific issues are resolved.

### ✅ Section 5 Checklist
- [ ] `/health` endpoint live and monitored
- [ ] `docs/pilot_feedback.md` created and used for the first week
- [ ] One-week metrics review completed, decision made on next steps

---

## Appendix: Full Combined Checklist

Everything above, in one place, to sign off Phase 4 as complete:

- [ ] Live taxonomy/SKU data fully re-synced and confirmed (§1)
- [ ] CSV mapping re-verified against a fresh real export (§1)
- [ ] First real batch executed in Full Review Mode with all post-import checks passed (§2)
- [ ] Rollback procedure tested at least once (§2)
- [ ] Daily workflow run start-to-finish without help (§3)
- [ ] Maintenance schedule set (§3)
- [ ] Training session completed (§4)
- [ ] Troubleshooting sheet accessible (§4)
- [ ] Uptime monitoring live (§5)
- [ ] Feedback log in use (§5)
- [ ] One-week metrics review completed (§5)

**Only once every box above is checked is the system considered fully handed over for independent daily use.**
