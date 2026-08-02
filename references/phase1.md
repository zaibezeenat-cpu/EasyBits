
# Phase 1: Verified Master Plan (Corrected v7.0)

**Project:** Enterprise-Level AI Agentic E-Commerce Workflow (LangGraph)
**Version:** 8.0 — Production Lock (SEO formatting rules brought in line with the actual implemented `seo_validator.py`/`writer.py`/`html_sanitizer.py`; supersedes v7.1's §6 entirely, not layered alongside it), with v3.0/v3.1 corrections layered on top (see below and §6.1/§6.8).

**Changelog v3.0 → v3.1 (Thin-Content Guard, code-level SEO audit finding, not a spec error being corrected):** Added check #13, `content_length_minimum` — concatenated body copy must be ≥ 200 words, per e-commerce SEO best practice (short, generic product copy reads as thin content to Google regardless of how clean the metadata is). Nothing previously enforced a floor on content length. `writer.py`'s prompt now also asks for a 40-word-minimum hero paragraph and 25-word-minimum per feature text. See §6.8 item 13.

**Changelog v7.1 → v8.0 (Production Lock):** Replaced the 10–13 comma-separated focus-keyword rule with a single Focus Keyword locked to the exact Product Name (no stacking). Replaced the ambiguous "`| Best Price`" title format with a deterministic, category-aware title builder (the "Boss Title Rule" for Air Conditioners, a power-word fallback for every other category — no LLM drift, no missing suffix, ever). Replaced "meta description under 155 chars, ends with !" with a strict 151–155 character window that must begin with the focus keyword, mention the warranty phrase, and end with a fixed per-category CTA. Added a formal LSI Keyword rule: exactly 3, embedded as plain text (never inside `<strong>`/`<b>`/a heading tag) — Rank Math doesn't detect a keyword it can't read as plain text. See §6.1, §6.2, §6.8.

**Changelog v7.0 → v7.1:** Replaced the static "pre-registered official URL per brand" model with dynamic discovery: Agent 1 now searches the web for each product, prefers a result whose domain matches the brand (treated as "official"), falls back to Japan Electronics/Surmawala only if no matching official domain is found, and flags to Manual Review if neither is found — it never falls back to an arbitrary/unverified search result. See §5.3 and §9.
**Date:** July 2026 | **Location:** Karachi, Pakistan
**Owner:** Product & Inventory Manager, kiachahye.pk (WordPress WooCommerce, WoodMart theme, Rank Math SEO)

**Changelog v6.0 → v7.0:** Fixed `Categories` hierarchy rule against verified real CSV sample (was wrong). Fixed Template A image-block count (2→3, verified). Added Category→Spec-Fields schema (previously undefined). Added no-hallucination + source-citation contract for Agent 1. Added duplicate-SKU pre-export guard. Softened keyword-density rule to avoid stuffing/duplicate-pattern risk. Added §0 Pre-Build Verification Checklist. Split success metrics. Added LLM cost line, secrets note, variant-product triage, warranty override, out-of-stock override.

---

## 0. Pre-Build Verification Checklist (Do Before Writing Any Code)

These are facts that must be confirmed from the live site, not assumed — get them before Phase 2 (build) starts:

1. Export **one real product** from wp-admin → Products → Export as an actual `.csv` file (not copy-pasted). Diff every header/meta key against §8.7 below.
2. Category parent mapping beyond `Home Appliance > Microwave Oven` — **not a manual export-and-write-down task.** The Taxonomy Manager (`phase2.md` §5.2) shows the tree with `needs_confirmation` flags and lets you set each `parent_id` inline, live, whenever you get to that category. Nothing blocks starting the build over this.
3. Brand casing — **also not a manual spreadsheet task.** Confirmed real casing so far: `DAWLANCE` (all caps, from the verified sample). The Taxonomy Manager's `casing_confirmed` toggle is where the rest get confirmed, one at a time, live — not an upfront full-catalog audit.
4. Export the current **SKU list** of all live products, to seed the duplicate-SKU guard (§8.6).
5. **RESOLVED 2026-07-21.** `Item` is a confirmed real top-level category (now seeded active). `Inverter` is **not** a category at all — it was invented in this document, reached the database, and matched every "Inverter AC" product; it has been removed. See §9.2 for the authoritative 26-category list.
6. Confirm the exact WooCommerce Brands plugin in use (Perfect WooCommerce Brands / YITH / other) — affects whether `Brands` is a plain CSV column or requires a different import path.

---

## 1. The Origin Story: Why We're Building This

Manual workflow today: receive raw model numbers + short titles → search each online across multiple sources → extract capacity/features/dimensions/warranty → cross-reference prices (official → Japan Electronics → Surmawala → estimate) → prompt a generic AI for SEO/HTML → fight hallucinations and broken HTML → manually cross-check every field across 4+ places it appears → build the CSV by hand → import and pray.

**Current benchmark:** ~8.5 hours for 21 products (~24 min/product), almost entirely spent on verification and formatting fixes.

**Core insight:** the manual re-verification step is the real bottleneck, not the writing. A system that produces content but not source citations for review just moves the bottleneck, it doesn't remove it — this drives several fixes below (§5.2).

---

## 2. Objective & Scope

**Objective:** an AI-driven workflow producing WooCommerce-ready CSVs with a built-in, multi-layer verification system, so the human's role shifts from "redo everything" to "approve a short list of flagged items with sources attached."

**V1 Scope Lock:**
- **Simple products only.** If a raw input item is detected as variant-shaped (multiple sizes/colors under one model line), it is auto-flagged to Manual Review, never force-processed as a Simple product (v6.0 gap — v7.0 fix).
- Image creation stays manual for V1; system generates placeholders.
- Cross-sells and Upsells deferred to V2.

---

## 3. Core Engine: Multi-Agent System (LangGraph)

| Component | Role |
|---|---|
| **Agent 1 — Extractor** | Dynamically discovers sources via web search (no pre-registered per-brand URL list, §5.3), then extracts facts into a strict schema per §7.7's category-specific field list. Never infers a missing fact (§5.2). Attaches a source URL to every fact. |
| **Agent 2 — Writer** | Fills content template placeholders using Agent 1's cited facts + SEO rules. Outputs structured JSON only, never raw HTML. |
| **Agent 3 — Reviewer** | Cross-checks Agent 2 vs. Agent 1, SEO rules, template completeness, Warranty Consistency Rule. Runs programmatic SEO validation. |
| **Escalation Handler** | **v7.0 fix:** distinguishes failure type. Agent-1 (extraction) failures — missing facts, unreachable source, conflicting facts — route straight to Manual Review, no retry (retrying doesn't fix a source problem). Agent-2/Agent-3 (writing/review-rule) failures get up to 3 Writer↔Reviewer retry cycles before Manual Review. |
| **HTML Sanitization Layer** | Deterministic Python function; `html.escape()` on all AI JSON strings before template merge. |
| **Specs Table Renderer** | Deterministic; renders Agent 1's cited facts into the category's spec-row schema (§7.7), no LLM. |
| **Short Description Renderer** | Deterministic. |
| **Product Name Builder** | Deterministic, naming formula (§7.8). |
| **CSV Assembler** | Deterministic. Maps fields to the verified 49-column WooCommerce format, applies taxonomy locks, runs the duplicate-SKU guard (§8.6), writes via Python's `csv` module with `QUOTE_ALL` (not manual comma-counting). |

---

## 4. Model & API Strategy

**Extractor:** `gemini-2.5-flash-lite` or `gemini-3.5-flash`. **Writer/Reviewer:** `openai/gpt-oss-120b` on Groq. Verify exact model IDs against provider docs immediately before deploy — do not trust names written here as final.

**Design rule:** never hardcode a model name; store the model ID in a config table; wrap every call in try/except for deprecation errors. Define one fallback provider per role in case of an outage — a single-provider dependency is a single point of failure for a system tied to daily production work.

**Rate limiting:** exponential backoff on 429s; 2-second delay between products; sequential in V1. Scraping requests need their own delay/jitter, separate from LLM rate limiting — rapid sequential scraping from one IP is what triggers anti-bot blocks in the first place.

**Cost:** hosting/DB $17–58/month (§11) **plus** LLM API token cost, estimated separately per product batch once real prompt sizes are known from the pilot (§15) — do not treat $17–58/month as the total operating cost.

---

## 5. Accuracy Strategy — Layered, Not Absolute

### 5.1 Layer 1: Schema Validation

Strict `pydantic` models reject malformed output structurally.

### 5.2 Layer 2: No-Hallucination Contract + Source Citation (v7.0, was missing)

Agent 1 must emit `null`/`UNKNOWN` for any fact it cannot verify from a fetched source — it must never infer, estimate, or pattern-match a plausible value. Every extracted fact carries the source URL it came from. This is stored and shown in the Human QA Panel next to the field it supports. **This is the single highest-leverage fix in this document**: it's what actually cuts the human's re-verification time, versus a system that just hides the sourcing and asks for trust.

### 5.3 Layer 3: Cross-Source Conflict Resolution + Dynamic Source Discovery (v7.1)

**No pre-registered per-brand URL list.** Agent 1 discovers sources live, per product, via web search — this is what keeps the system from needing you to maintain a URL for every brand forever. The discovery order is strict and never falls back to an unverified guess:

1. **Search the web** for `[brand] [model number]`.
2. **Prefer a result whose domain matches the brand** (e.g. a Dawlance product page on a `dawlance.*` domain) — treated as "official." This is a deterministic domain-match check, not an LLM judgment call.
3. **If no matching official domain appears in the results, fall back to Japan Electronics or Surmawala** (still the two named, trusted reference sites) if either appears in the results for that product.
4. **If neither an official-domain match nor a trusted secondary source turns up anything usable, the product is flagged to Manual Review** with reason "no reliable source found" — the system never falls back further to an arbitrary/unranked search result just to have *something*.

**Trusted secondary sources are admin-editable, not hardcoded.** Japan Electronics and Surmawala are the two seeded by default, but this is a plain list (domain + label) managed via Settings → Trusted Secondary Sources — add, remove, or deactivate one without touching code.

Source priority for facts (once sources are found): official brand site → Japan Electronics → Surmawala → (price only) user estimate. If two found sources disagree on any fact — spec, dimension, or price — the product is flagged for human resolution, not silently resolved by picking the higher-priority source. Silent resolution hides exactly the kind of discrepancy the user currently catches manually.

### 5.4 Layer 4: Cross-Check (Reviewer)

Agent 3 compares Agent 2's writing against Agent 1's cited facts.

### 5.5 Layer 5: Warranty Consistency Rule (Critical)

Warranty appears in 4 places (short description, long description, specs table, FAQ Q5). Single source of truth: the Brand-Category Warranty Matrix, stored as a clean phrase (e.g. `"1-Year Brand Warranty"`, not a full sentence) so it drops cleanly into all 4 templates. A per-product manual override is allowed (e.g. a promotional bundle warranty that differs from the brand default) — Agent 3 still enforces the exact-match check across all 4 locations against whichever value (matrix default or override) is active for that product. **Re-audit the Warranty Matrix quarterly** — brand policies change, and a stale warranty string is a customer-facing liability, not just an SEO detail.

### 5.6 Layer 6: Bounded Retry (v7.0: retyped per §3's Escalation Handler)

Up to 3 Writer↔Reviewer cycles — only for writing/review-rule failures, never for extraction failures (those skip straight to Manual Review, see §3).

### 5.7 Layer 7: Human Quick-QA (v7.0: two modes, was one)

- **Full Review Mode** (all fields + source citations visible): used during pilot and any period the user hasn't yet built trust in the system (ties to the "Gradual Trust Reduction" step in §15).
- **Quick Review Mode** (AI-flagged fields only): available once the pilot has demonstrated a stable low error rate.

### 5.8 Layer 8: Manual Review Required

Anything failing all automated checks (or auto-routed there per §3/§5.3) goes to a dedicated queue with the **specific reason attached** (e.g. "source unreachable," "spec conflict: capacity 20L vs 21L," "variant-shaped input"). Never force-published. A basic notification (dashboard badge count, minimum) prevents the queue from silently piling up.

---

## 6. The Enterprise SEO Engine — Rank Math Blueprint

### 6.1 Keyword Generation (v3.0 correction — reverses part of v8.0's "exactly one keyword" lock)

**v8.0 got this wrong.** It locked `Meta: rank_math_focus_keyword` to a single keyword with no comma-stacking, reasoning that Rank Math only supports one focus keyword. **Confirmed directly against the live Rank Math panel UI (not a guess):** Rank Math natively supports a primary keyword plus secondary/related keywords as pills in its own interface, and its own scoring explicitly says *"Keyword Density... the Focus Keyword **and combination** appears N times."* Real reference exports confirm the same pattern: `Meta: rank_math_focus_keyword` = Product Name + 3 more comma-separated phrases.

- **Primary keyword:** still deterministically the exact Product Name — this part of v8.0 was right and is unchanged (not LLM output, never drifts).
- **Exported focus keyword field = primary + 3 LSI keywords, comma-joined.** `build_focus_keyword_field()` assembles this at CSV-export time — no new keywords are generated for this; it reuses the same 3 LSI keywords the Writer already produces for the body/alt-text (below), so there's no duplicate generation step and no risk of the two lists disagreeing.
- **LSI Keywords: exactly 3.** The Writer generates exactly 3 secondary/semantically-related keywords and weaves each one natively into the body copy (hero paragraph or feature text) as **plain text** — never inside a `<strong>`, `<b>`, or heading tag, since Rank Math cannot detect a keyword it can't read as plain prose. `html_sanitizer.py::strip_lsi_keyword_formatting()` strips any such wrapper tags found immediately around one of these 3 exact strings as a safety net, but the Writer is instructed to never wrap them in the first place.
- **Image alt text:** each of the (up to 3) product image alt attributes must be exactly the Focus Keyword or one of the 3 LSI keywords — nothing else.

### 6.2 Rank Math Placement Rules (v8.0 Production Lock)

| Rule | Target | Why |
|---|---|---|
| URL slug | ≤ 75 characters | Rank Math flags long slugs |
| `Name` | ≤ 44 characters | Keeps slug safely under 75 |
| `Meta: rank_math_title` — **"Boss Title Rule" (v3.0: universal, not AC-only)** | Deterministic, category-aware, never LLM-written: `"[Brand] [Capacity] [Series] [SKU] [Premium Category Suffix]"` for every category with a registered suffix (e.g. AC → `"...DC Inverter Heat & Cool Split Air Conditioner"`, Microwave Oven → `"...Digital Grill Microwave Oven"`, Refrigerator → `"...Inverter Direct Cool Refrigerator"` — the full registry lives in `seo_title_builder.py::CATEGORY_TITLE_DESCRIPTORS`, one entry per category, edited there not in the LLM prompt). Any category not yet registered falls back to `"[Focus Keyword] \| Buy Smart"` rather than guessing a suffix. No character-length cap is enforced — the literal descriptors legitimately run well past 60 characters; the format itself is the compliance signal, not a length window. **Known limitation:** a per-category suffix is a generalization (e.g. assumes Split + Inverter + Heat&Cool for every AC) — an atypical product within a category (a Floor Standing unit, a non-inverter fridge) may get a technically-generic title suffix; the specs table and description still state the real configuration correctly, so this is an SEO-title nicety risk, not a product-data accuracy risk. | Deterministic titles guarantee 100/100 title compliance every time — no LLM drift, no missing suffix, no inconsistent format across the catalog. |
| First 10% rule | Focus Keyword in first 10% of `hero_paragraph` | Matches Rank Math's own test |
| **Keyword density** | Focus Keyword appears **naturally, typically 3–6 times** across all body text combined, varying phrasing on later repeats | Forcing an *exact* count of a long product-name phrase reads as keyword-stuffed under Google's spam policies even while it scores green on Rank Math's own checklist metric — a high internal score is not the same as ranking well. |
| Meta description | **Strictly 151–155 characters.** Must (1) begin with the exact Focus Keyword, (2) mention the warranty's real duration number(s) (exact stored phrase wording not required — see v3.0 note below), (3) end with a fixed, category-specific CTA sentence (capacity-aware where relevant, e.g. `"Buy the best {actual capacity} AC in Pakistan today."` — never a hardcoded tonnage for every product in a category). **v3.0 correction:** a long Boss-Rule focus keyword can already consume most of the 151–155 budget, leaving no room for the full compound warranty sentence too — real reference examples abbreviate it (e.g. `"Warranty: 10-yr."`). The check now requires every duration number from the real warranty phrase to appear somewhere in the description (so a duration can never be silently dropped or invented), not an exact-string match. | Matches Rank Math's own length test with zero tolerance either side of the window, and every clause is independently checkable, not just a length bound. |

### 6.3 Content Structure

- **Short Description:** Transactional. Hook → top 3 features → warranty → CTA.
- **Long Description:** Informational. Structured with H2/H3, filled into the selected template. Specs table is separate.

### 6.4 Q&A Content — GEO-Optimized

- 5 questions per product.
- **Q5 (FIXED):** Always "What is the official warranty?" → Answer = the exact active warranty phrase (matrix default or per-product override, §5.5).

### 6.5 Product Schema (JSON-LD)

Auto-generated by Rank Math Pro from imported data. Verify during staging that price/availability/brand resolve correctly in the generated schema — don't assume it's correct just because the plugin claims to auto-generate it.

### 6.6 Internal Pre-Flight Scoring

Agent 3 computes its own weighted score. If below 90, product goes back through the writer/reviewer retry loop (not the extraction-failure path).

### 6.7 On `Meta: rank_math_seo_score` (v7.0, new caveat)

The verified real sample hardcodes this to `95` directly in the CSV. This is very likely **cosmetic only** — Rank Math recalculates the actual score client-side the next time the product is opened and saved in wp-admin, and a raw imported number may not reflect a real analysis. Do not treat a pre-set `95` as a verified pass; confirm the real behavior once against a staging import before relying on it for the "95+" success metric (§16).

### 6.8 Programmatic SEO Validation Layer (v8.0 Production Lock, v3.1 thin-content addition — matches `seo_validator.py` exactly)

Strict deterministic checks before content reaches CSV — implemented 1:1 in `backend/app/graph/seo_validator.py::validate_seo_rules()`:

1. **Product Name Check:** `Name` ≤ 44 characters.
2. **Slug Check:** ≤ 75 characters.
3. **Primary Focus Keyword Lock:** the *primary* keyword (used internally for the first-10%-rule, alt-text validation, etc.) is exactly one keyword, identical to the Product Name, no comma-stacking. The *exported CSV field* additionally appends the 3 LSI keywords via `build_focus_keyword_field()` (§6.1, v3.0) — that combination happens downstream at CSV-assembly time, after this check has already passed on the primary keyword alone, so this check's logic is unchanged even though the final CSV value does contain commas.
4. **SEO Title — Boss Title Rule:** title matches the category's registered literal descriptor, or ends with the power-word marker (§6.2).
5. **Meta Description Length:** strictly 151–155 characters.
6. **Meta Description Begins With Focus Keyword.**
7. **Meta Description Mentions Warranty:** every duration number from the real warranty phrase must appear (exact sentence wording not required, v3.0 correction).
8. **Meta Description Ends With CTA:** the fixed, capacity-aware CTA sentence for the category, resolved once and reused identically by both the Writer's prompt and this check (never recomputed independently, so the two can't silently drift onto different claims).
9. **LSI Keyword Count:** exactly 3.
10. **LSI Keywords Present in Body:** all 3 appear as plain text in the concatenated content.
11. **Image Alt Text Valid:** every image alt attribute is exactly the Focus Keyword or one of the 3 LSI keywords.
12. **First 10% Rule:** Focus Keyword in first 10% of text.
13. **Content Length Minimum (v3.1, closes a real gap):** concatenated body copy (hero paragraph + all feature texts + bullets + FAQ answers) must be ≥ 200 words. Nothing previously enforced a lower bound on content length — a technically-valid-but-thin response (short hero, short feature texts) could still pass every other check while reading as thin content to Google. `writer.py`'s prompt now also instructs a 40-word-minimum hero paragraph and 25-word-minimum per feature text so the LLM aims well above the floor, not right at it.
14. **Warranty Consistency Check:** Exact string match across all 4 locations (§5.5).
15. **Price Check:** Regular and Sale price must not be empty, sale < regular.
16. **Template Completeness:** No empty placeholders.
17. **Duplicate-SKU Check:** `SKU` not already present in the live-catalog SKU export (§8.6).

---

## 7. Content Template System & Output Schema

### 7.1 Why This Matters

The AI never writes raw HTML. The AI fills placeholders in HTML skeletons. Code controls markup, the model controls text.

### 7.2 Short Description Template

**Template:**

```
<p>[CATEGORY_HOOK] the <strong>{{PRODUCT_NAME}}</strong>. Designed for modern homes, this premium appliance features {{FEATURE_1}}, {{FEATURE_2}}, and {{FEATURE_3}}. With [extra_feature], it ensures effortless and secure operation. Backed by a {{WARRANTY}}.</p>
```

`{{WARRANTY}}` must be the clean matrix phrase (§5.5), e.g. `"1-Year Brand Warranty"` — never a full sentence, to avoid the double-"warranty" wording seen in the old manual process's real sample output ("...backed by a warranty of 1-year brand warranty").

### 7.3 Long Description Templates (v7.0: Template A corrected to verified structure)

**Dynamic Template Fallback Rule (Critical):**
If the user selects Template A ("With Images"), but Agent 1 extracts fewer than **3** images (v7.0 fix — verified real Template A uses 3 image slots, not 2 as previously documented), the system will **automatically and silently fallback to Template B ("Without Images")** for that specific product. This prevents broken `<img>` tags on the frontend. A notification will be shown in the Quick-QA panel: _"Switched to Template B due to missing images."_

**Template A — "With Images" — 3 alternating image/feature blocks (v7.0 corrected):**
Structure verified against the real working sample: hero heading/paragraph → [image 1 | feature block 1] → [feature block 2 | image 2] → [image 3 | feature block 3] → Features bullet list → FAQs. The Python renderer strictly uses this exact HTML structure and inline CSS; the AI only provides text for the placeholders.

```html
<h2 style="color: #561491;">{{HERO_HEADING}}</h2>
<p>{{HERO_PARAGRAPH}}</p>
<div
  style="display: flex; flex-wrap: wrap; align-items: center; margin-top: 30px; margin-bottom: 30px; gap: 20px;"
>
  <div style="flex: 1 1 300px;">
    <img
      src="[INSERT_IMAGE_URL_1]"
      alt="{{PRODUCT_NAME}}"
      style="width: 100%; height: auto; border-radius: 8px; border: 2px solid #eaeaea;"
    />
  </div>
  <div style="flex: 1 1 300px;">
    <h3
      style="color: #561491; border-bottom: 2px solid #F7A800; padding-bottom: 5px;"
    >
      {{FEATURE_1_HEADING}}
    </h3>
    <p>{{FEATURE_1_TEXT}}</p>
  </div>
</div>
<div
  style="display: flex; flex-wrap: wrap; align-items: center; margin-bottom: 30px; gap: 20px;"
>
  <div style="flex: 1 1 300px;">
    <h3
      style="color: #561491; border-bottom: 2px solid #F7A800; padding-bottom: 5px;"
    >
      {{FEATURE_2_HEADING}}
    </h3>
    <p>{{FEATURE_2_TEXT}}</p>
  </div>
  <div style="flex: 1 1 300px;">
    <img
      src="[INSERT_IMAGE_URL_2]"
      alt="{{PRODUCT_NAME}}"
      style="width: 100%; height: auto; border-radius: 8px; border: 2px solid #eaeaea;"
    />
  </div>
</div>
<div
  style="display: flex; flex-wrap: wrap; align-items: center; margin-bottom: 30px; gap: 20px;"
>
  <div style="flex: 1 1 300px;">
    <img
      src="[INSERT_IMAGE_URL_3]"
      alt="{{PRODUCT_NAME}}"
      style="width: 100%; height: auto; border-radius: 8px; border: 2px solid #eaeaea;"
    />
  </div>
  <div style="flex: 1 1 300px;">
    <h3
      style="color: #561491; border-bottom: 2px solid #F7A800; padding-bottom: 5px;"
    >
      {{FEATURE_3_HEADING}}
    </h3>
    <p>{{FEATURE_3_TEXT}}</p>
  </div>
</div>
<h3
  style="color: #561491; border-bottom: 2px solid #F7A800; padding-bottom: 8px; margin-top: 30px; margin-bottom: 15px;"
>
  Your Favorite Features
</h3>
<ul>
  {{FEATURES_BULLETS}}
</ul>
<h3
  style="color: #561491; border-bottom: 2px solid #F7A800; padding-bottom: 8px; margin-top: 30px; margin-bottom: 20px;"
>
  FAQs
</h3>
{{FAQ_BLOCKS}}
```

**Template B — "Without Images" Canonical HTML Skeleton (unchanged from v6.0):**
Hero intro, 1 descriptive section without image, Features list, FAQs. Admin can edit this and other templates easily in the frontend UI.

```html
<h2 style="color: #561491;">{{HERO_HEADING}}</h2>
<p>{{HERO_PARAGRAPH}}</p>
<h2 style="color: #561491;">{{SECTION_2_HEADING}}</h2>
<p>{{SECTION_2_PARAGRAPH}}</p>
<h3
  style="color: #561491; border-bottom: 2px solid #F7A800; padding-bottom: 8px; margin-top: 30px; margin-bottom: 15px;"
>
  Your Favorite Features
</h3>
<ul>
  {{FEATURES_BULLETS}}
</ul>
<h3
  style="color: #561491; border-bottom: 2px solid #F7A800; padding-bottom: 8px; margin-top: 30px; margin-bottom: 20px;"
>
  FAQs
</h3>
{{FAQ_BLOCKS}}
```

**FAQ Block Canonical Format (Strict Styling - Repeated exactly 5 times):**

```html
<div style="margin-bottom: 15px;">
  <strong
    style="font-size: 16px; color: #561491; font-family: var(--wd-title-font);"
    >Q{{N}}: {{FAQ_Q}}</strong
  >
  <p style="margin-top: 5px; margin-bottom: 0;">
    <strong>A:</strong> {{FAQ_A}}
  </p>
</div>
```

(Where N = 1 to 5. FAQ Q5 is ALWAYS fixed: "What is the official warranty?" -> Answer: "It comes with a {{WARRANTY}} provided by {{BRAND}}.")

### 7.4 Frontend: Template Selection at Input Time

Dropdown listing all active templates from the database, passed to Agent 2.

### 7.5 Template Management Screen

Admin screen to add/edit/preview HTML skeletons without touching code.

### 7.6 Agent 2's Revised Job

Output is a JSON object mapping placeholder names to filled content. Backend merges JSON into the chosen HTML skeleton.

### 7.7 Specs Table — Fully Separate, Not AI-Written (Editable in Frontend)

**Canonical specs table HTML template (matches verified examples exactly):**

```html
<table
  class="shop_attributes"
  style="width: 100%;border-collapse: collapse;margin-bottom: 25px;font-size: 14px"
>
  <thead>
    <tr style="border-bottom: 1px solid #eaeaea">
      <th
        style="text-align: left;padding: 8px 4px;width: 35%;color: #111111;font-family: var(--wd-title-font)"
      >
        SPECIFICATION
      </th>
      <th
        style="text-align: left;padding: 8px 4px;color: #111111;font-family: var(--wd-title-font)"
      >
        DETAILS
      </th>
    </tr>
  </thead>
  <tbody>
    {{SPECS_ROWS}}
  </tbody>
</table>
```

**Standard Row Template:**

```html
<tr style="border-bottom: 1px solid #eaeaea">
  <th
    style="text-align: left;padding: 8px 4px;color: #555555;font-weight: normal;vertical-align: top"
  >
    {{SPEC_LABEL}}
  </th>
  <td style="padding: 8px 4px;color: #555555;vertical-align: top">
    {{SPEC_VALUE}}
  </td>
</tr>
```

**Warranty Row Template (Bold - Always the last row):**

```html
<tr style="border-bottom: 1px solid #eaeaea">
  <th
    style="text-align: left;padding: 8px 4px;color: #555555;font-weight: bold;vertical-align: top"
  >
    Warranty
  </th>
  <td
    style="padding: 8px 4px;color: #555555;vertical-align: top;font-weight: bold"
  >
    {{WARRANTY}}
  </td>
</tr>
```

Table class `shop_attributes`, headers `SPECIFICATION` and `DETAILS`, standard rows font-weight normal, final Warranty row font-weight **bold**. Admin can choose and edit spec table templates in the frontend.

**Category → Expected Spec Fields (v7.0, new — this schema did not exist in v6.0):**

Agent 1 needs a defined list of which facts to extract per category — without it, extraction is inconsistent product to product. Seeded from the one verified real example; every other category needs the user's input during Phase 0 (§0 item 5/6) rather than being guessed:

| Category | Expected Spec Fields |
|---|---|
| Microwave Oven | Brand, Model Number, Appliance Type, Capacity, Control Panel, Features, Warranty *(CONFIRMED from real sample)* |
| *(every other category)* | Defined via the Taxonomy Manager's spec-schema editor, one category at a time, whenever you're about to start processing it — **not a document you write out in advance for every category up front.** |

**The hard rule that matters (unchanged, this is the actual safety mechanism):** a category with no defined spec schema routes its products straight to Manual Review with reason `missing_category_schema` — Agent 1 never improvises one. That's enforced in code (`phase2.md` §3.3/§7.7), not by a checklist you have to complete first. Define a category's fields in the Taxonomy Manager right before you process your first product in that category — the system tells you if you forgot, it doesn't let you find out the hard way. Every category-specific list must always end with a bold `Warranty` row, matching the verified pattern.

### 7.8 Product Name Construction (Strict Rules)

**Golden Rule Formula:** `[Brand] [Capacity] [Model] [Type]`

**Formatting Rules:**

- Capacity must be clean (e.g., `1 Ton` instead of `1.0 Ton`, `20L` instead of `20 Liters`).
- Type should reflect the exact product nature based on the category (e.g., `Inverter Split Air Conditioner`, `Grill Microwave`, `Solo White Microwave`).
- **Strict Length Limit:** The final Name MUST be **under 44 characters** to ensure the URL slug stays safely under 75 characters. If the standard formula exceeds 44 characters, the system must abbreviate the Type (e.g., "Air Conditioner" -> "AC", "Microwave Oven" -> "Microwave") until it fits.

**Example:**

- Ideal: `TCL 1 Ton 12 SVN-AI-CO-31G/S Inverter Split AC` (43 chars - Pass)
- Ideal: `Homage 20L HDG-201S Grill Microwave` (36 chars - Pass)

### 7.9 Breadcrumb Title

`Meta: rank_math_breadcrumb_title` = Product Name (same as Section 7.8).

### 7.10 Tags Generation Strategy (Strict 3-Tag Rule)

Tags are generated deterministically — no AI, no long-tail SEO keywords, no manual additions.

**Strict Formula:** `[Brand], [Category], HW`

**Rules:**

- Must contain EXACTLY these three tags, separated by commas.
- `[Brand]` is pulled **exactly as stored in the live taxonomy** (§0 item 3) — do not cosmetically normalize casing; a mismatch creates a duplicate WooCommerce term instead of reusing the existing one.
- `[Category]` is pulled exactly as written in the approved Category List.
- `HW` is permanently fixed for all products as internal identification.

**Examples:**

- Product: TCL Air Conditioner → Tags: `TCL, Air conditioner, HW`
- Product: Dawlance Microwave → Tags: `DAWLANCE, Microwave Oven, HW`

---

## 8. Complete CSV Field Mapping

### 8.1 Static Default Fields (Same For Every Simple Product)

| CSV Column                                        | Value           | Notes                     |
| ------------------------------------------------- | --------------- | ------------------------- |
| `Type`                                            | `simple`        | V1 scope                  |
| `Published`                                       | `-1`            | **Draft** (Safety)        |
| `Is featured?`                                    | `0`             |                           |
| `Visibility in catalog`                           | `visible`       |                           |
| `Tax status`                                      | `none`          | Matched from verified CSV |
| `Tax class`                                       | _(empty)_       |                           |
| `In stock?`                                       | `1`             | **v7.0:** optional per-product override for known-out-of-stock intake items |
| `Stock`                                           | _(empty)_       |                           |
| `Low stock amount`                                | _(empty)_       |                           |
| `Backorders allowed?`                             | `0`             |                           |
| `Sold individually?`                              | `0`             |                           |
| `Allow customer reviews?`                         | `1`             |                           |
| `Purchase note`                                   | _(empty)_       |                           |
| `Shipping class`                                  | _(empty)_       |                           |
| `Download limit`                                  | `0`             |                           |
| `Download expiry days`                            | `0`             |                           |
| `Parent`                                          | _(empty)_       |                           |
| `Grouped products`                                | _(empty)_       |                           |
| `Upsells`                                         | _(empty)_       | V2                        |
| `Cross-sells`                                     | _(empty)_       | V2                        |
| `External URL`                                    | _(empty)_       |                           |
| `Button text`                                     | _(empty)_       |                           |
| `Position`                                        | `0`             |                           |
| `Date sale price starts`                          | _(empty)_       |                           |
| `Date sale price ends`                            | _(empty)_       |                           |
| `Meta: _woodmart_product_custom_tab_title`        | `Specification` |                           |
| `Meta: _woodmart_product_custom_tab_priority`     | `20`            |                           |
| `Meta: _woodmart_product_custom_tab_content_type` | `text`          |                           |

### 8.2 User-Input Fields (Entered Per Product)

| CSV Column      | Source                    | Validation          |
| --------------- | ------------------------- | -------------------- |
| `SKU`           | User input (Model Number) | Required, unique, and (v7.0) checked against the live-catalog SKU export — see §8.6 |
| `Regular price` | User input                | Required, > 0, numeric only (reject "Rs"/commas) |
| `Sale price`    | User input                | Required, < Regular  |

**Price reference system:** Agent 1 dynamically discovers and scrapes an official/Japan Electronics/Surmawala source (§5.3's discovery order) to show suggestions — no pre-registered URL needed. **v7.0:** if the scraped official price differs sharply (e.g. >15%) from the user's entered price, surface a warning without blocking entry — it may catch a typo or a stale scrape.

### 8.3 AI-Generated Fields (Agent 2 → Template → Renderer)

| CSV Column                      | Produced By                | Template Used                    |
| -------------------------------- | --------------------------- | --------------------------------- |
| `Short description`             | Short Description Renderer | Short Description Template (7.2) |
| `Description`                   | Template merge (A or B)    | Template A or B (7.3)            |
| `Meta: rank_math_focus_keyword` | Deterministic primary (name builder) + Agent 2's 3 LSI keywords | Primary keyword = Product Name; exported CSV cell is the primary keyword + 3 LSI keywords, comma-joined via `build_focus_keyword_field()` (v3.0, §6.1) |
| `Meta: rank_math_title`         | Deterministic (`seo_title_builder.py`) | "Boss Title Rule" / power-word format, not Agent 2 output (§6.2) |
| `Meta: rank_math_description`   | Agent 2                    | Strict 151-155 chars, begins with focus keyword, mentions warranty, ends with fixed CTA (§6.2) |

### 8.4 Deterministic-Builder Fields (Python Functions, No AI)

| CSV Column                         | Produced By                | Logic                                           |
| ----------------------------------- | ---------------------------- | ------------------------------------------------- |
| `Name`                             | Product Name Builder (7.8) | `[Brand] [Capacity] [Model] [Type]` (<44 chars) |
| `Categories`                       | Taxonomy Mapping Table (9) | `"[Parent] > [Category]"` — **v7.0 fix, see §8.7** |
| `Brands`                           | Taxonomy Mapping Table (9) | Exact match from live Brands taxonomy (§0 item 3) |
| `Tags`                             | Tag Generator (7.10)       | Strict 3-Tag Rule: `[Brand], [Category], HW`    |
| `Weight (kg)`                      | Agent 1 (or 0)             |                                                  |
| `Length (cm)`                      | Agent 1 (or 0)             |                                                  |
| `Width (cm)`                       | Agent 1 (or 0)             |                                                  |
| `Height (cm)`                      | Agent 1 (or 0)             |                                                  |
| `Meta: rank_math_breadcrumb_title` | Product Name Builder       | Same as Name                                    |
| `Meta: rank_math_seo_score`        | _(empty or informational)_ | See §6.7 — treat as cosmetic, not a verified score |
| `Meta: rank_math_focus_keyword`    | Name Builder (v8.0) + Agent 2's LSI keywords | Primary keyword locked to exact Name, single keyword, no stacking; exported CSV cell also appends the 3 LSI keywords (v3.0 correction, §6.1) |
| `Meta: rank_math_title`            | `seo_title_builder.py` (v8.0) | "Boss Title Rule" / power-word format (§6.2) — moved here from §8.3 (AI-Generated) since v8.0 makes both fields deterministic, not Agent 2 output |

### 8.5 Images Field

Left **empty** in CSV for V1. Manual upload after import.

### 8.6 CSV Escaping, Structural Safety & Duplicate-SKU Guard (v7.0 revised)

- **Duplicate-SKU Guard (v7.0, new, critical):** before any product reaches "Ready for QA," its `SKU` is checked against an exported list of existing live-catalog SKUs (§0 item 4). A match blocks export and routes to Manual Review with reason "SKU collision with live product [ID]" — WooCommerce's importer matches/updates products by SKU, so an unnoticed collision would silently overwrite a live published product.
- **CSV writing method (v7.0 fix):** use Python's `csv` module with `QUOTE_ALL` — this correctly handles column counts, embedded commas, and quote-escaping by construction. This replaces the old "11-Comma Rule" manual comma-counting heuristic, which was a fragile reinvention of a problem the standard library already solves.
- **HTML Sanitization Layer:** Before the CSV Assembler runs, all AI-generated JSON strings are passed through Python's `html.escape()`. This neutralizes any rogue double quotes (e.g., `It's a "great" product` becomes `It's a &quot;great&quot; product`), preventing malformed rows during CSV generation.

### 8.7 Complete CSV Column Reference (Master Checklist — 49 columns, order verified against a real working import sample)

| #   | CSV Column                                        | Source                 | Category       |
| --- | --------------------------------------------------- | ------------------------- | ---------------- |
| 1   | `ID`                                              | Empty                  | Skip           |
| 2   | `Type`                                            | Fixed: `simple`        | Static Default |
| 3   | `SKU`                                             | User input             | User Input     |
| 4   | `Name`                                            | Product Name Builder   | Deterministic  |
| 5   | `Published`                                       | Fixed: `-1`            | Static Default |
| 6   | `Is featured?`                                    | Fixed: `0`             | Static Default |
| 7   | `Visibility in catalog`                           | Fixed: `visible`       | Static Default |
| 8   | `Short description`                               | Renderer                | AI + Template  |
| 9   | `Description`                                     | Template merge          | AI + Template  |
| 10  | `Date sale price starts`                          | Empty                   | Static Default |
| 11  | `Date sale price ends`                            | Empty                   | Static Default |
| 12  | `Tax status`                                      | Fixed: `none`          | Static Default |
| 13  | `Tax class`                                       | Empty                   | Static Default |
| 14  | `In stock?`                                       | Fixed: `1` (overridable) | Static Default |
| 15  | `Stock`                                           | Empty                   | Static Default |
| 16  | `Low stock amount`                                | Empty                   | Static Default |
| 17  | `Backorders allowed?`                             | Fixed: `0`              | Static Default |
| 18  | `Sold individually?`                              | Fixed: `0`              | Static Default |
| 19  | `Weight (kg)`                                     | Agent 1                 | Deterministic  |
| 20  | `Length (cm)`                                     | Agent 1                 | Deterministic  |
| 21  | `Width (cm)`                                      | Agent 1                 | Deterministic  |
| 22  | `Height (cm)`                                     | Agent 1                 | Deterministic  |
| 23  | `Allow customer reviews?`                         | Fixed: `1`              | Static Default |
| 24  | `Purchase note`                                   | Empty                   | Static Default |
| 25  | `Sale price`                                      | User input              | User Input     |
| 26  | `Regular price`                                   | User input              | User Input     |
| 27  | `Categories`                                      | Taxonomy Table          | Deterministic  |
| 28  | `Tags`                                            | Tag Generator            | Deterministic  |
| 29  | `Shipping class`                                  | Empty                    | Static Default |
| 30  | `Images`                                          | Empty                    | Manual         |
| 31  | `Download limit`                                  | Fixed: `0`               | Static Default |
| 32  | `Download expiry days`                            | Fixed: `0`               | Static Default |
| 33  | `Parent`                                          | Empty                    | Static Default |
| 34  | `Grouped products`                                | Empty                    | Skip           |
| 35  | `Upsells`                                         | Empty                    | V2             |
| 36  | `Cross-sells`                                     | Empty                    | V2             |
| 37  | `External URL`                                    | Empty                    | Skip           |
| 38  | `Button text`                                     | Empty                    | Skip           |
| 39  | `Position`                                        | Fixed: `0`               | Static Default |
| 40  | `Brands`                                          | Taxonomy Table           | Deterministic  |
| 41  | `Meta: _woodmart_product_custom_tab_title`        | Fixed: `Specification`  | Static Default |
| 42  | `Meta: _woodmart_product_custom_tab_priority`     | Fixed: `20`              | Static Default |
| 43  | `Meta: _woodmart_product_custom_tab_content_type` | Fixed: `text`           | Static Default |
| 44  | `Meta: _woodmart_product_custom_tab_content`      | Specs Renderer           | Deterministic  |
| 45  | `Meta: rank_math_focus_keyword`                   | Primary keyword (Name Builder, deterministic) + 3 LSI keywords (Agent 2), joined by `build_focus_keyword_field()` (v3.0, §6.1) | Deterministic + AI Generated |
| 46  | `Meta: rank_math_title`                           | `seo_title_builder.py::build_seo_title()` — Boss Title Rule (v8.0 Production Lock); NOT written by the LLM | Deterministic  |
| 47  | `Meta: rank_math_description`                     | Agent 2                  | AI Generated   |
| 48  | `Meta: rank_math_seo_score`                       | Empty or informational   | See §6.7       |
| 49  | `Meta: rank_math_breadcrumb_title`                | Name Builder              | Deterministic  |

**49 columns, 49 mapped — order confirmed against a real working import sample.**

**`Categories` field rule — v7.0 CRITICAL FIX:** value is `"[Parent] > [Category]"` (e.g. `Home Appliance > Microwave Oven`), **not** a bare category string as v6.0 incorrectly stated ("no parent prepended"). The verified real sample proves the parent **is** prepended with `>`. Only the microwave example is confirmed today; the rest of §9.2's parent mapping fills in over time via the Taxonomy Manager (§9), live, not as a one-time precondition — a category with an unconfirmed parent simply routes its products to Manual Review rather than exporting a wrong hierarchy string, so there's nothing to "finish" before this table is trustworthy.

**Future/V2 note:** consider a `global_unique_id` (GTIN/barcode) column if Google Shopping/Merchant Center is ever used — not needed now.

---

## 9. Data, Pricing & Taxonomy Strategy (Strict Locks)

**§9.1/§9.2 below are seed/starting data, not a fixed list frozen into the code.** They're loaded once via `seed_taxonomy.py` (`phase2.md` §1) so the system isn't empty on day one, but every brand and category — including new ones you start selling later — is added, edited, activated, or deactivated live through the Taxonomy Manager (`phase2.md` §5.2). No code change, no redeploy, ever, just to add a brand or category.

- **Prices:** User manually inputs. AI never invents pricing. Reject non-numeric input.
- **Warranty:** Defaults from the Brand-Category Warranty Matrix (§5.5). Per-product override allowed. Quarterly re-audit required.
- **Brands:** The AI must select **strictly** from the official approved list, matched **exactly as stored in the live WooCommerce Brands taxonomy** — verify casing before assuming the list below needs "cleanup" (§0 item 3). This list is fully editable via the Frontend UI.
- **Categories:** The AI must select **strictly** from the official approved list. This list is fully editable via the Frontend UI.
- **Category Hierarchy Rule (v7.0 CORRECTED):** value is `"[Parent] > [Category]"` — the parent **is** prepended, per the verified real sample. (v6.0 stated the opposite; that was wrong.)

### 9.1 Official Brand List (verify exact casing against live taxonomy before build — do not normalize without checking, §0 item 3)

1. Anex | 2. Boss | 3. DAWLANCE | 4. EcoStar | 5. ELite | 6. Gaba National | 7. GFC | 8. GREE | 9. HAIER | 10. Hanco | 11. Homage | 12. Hotline | 13. Kenwood | 14. Login | 15. Midea | 16. NASGAS | 17. ORIENT | 18. Panasonic | 19. PEL | 20. Philips | 21. Royal Fans | 22. SG | 23. Super Asia | 24. TCL | 25. WestPoint Pakistan

*(v3.0: added `Gaba National` — confirmed present in the live catalog's own real export sample, a "Gaba National GNW-95023 Twin Tub Baby Washing Machine," not a guess.)*

*Casing above (mix of Title Case and ALL CAPS) is preserved as-is because the verified real sample shows `DAWLANCE` stored in all caps in the live taxonomy — this may be intentional/authoritative per term, not a documentation typo. Confirm each entry against the real Brands export (§0 item 3) before treating this list as final.*

### 9.2 Official Category List + Parent Mapping (AUTHORITATIVE — confirmed by the site owner 2026-07-21)

**This is the exact live WooCommerce taxonomy: 4 top-level categories, 16 Home Appliance
sub-categories, 6 Kitchen Appliances sub-categories = 26 total. Nothing may be added to it.**
A brand or category not on this list routes the product to Manual Review — it is never created
on the fly, because WooCommerce silently CREATES any unrecognised term on import, adding junk to
the live store. Locked by `backend/tests/unit/test_taxonomy_lock.py`.

Two entries previously invented in this document reached the database and caused real damage,
and have been removed: **"Inverter"** (matched every "Inverter AC", escalating them all) and
**"Water Heater"** (never existed on the live site).

| # | Category | Parent |
|---|---|---|
| 1 | Beauty | — (top-level) |
| 2 | Home Appliance | — (top-level) |
| 3 | Air conditioner | Home Appliance |
| 4 | Air cooler | Home Appliance |
| 5 | Air Purifier | Home Appliance |
| 6 | Deep Freezer | Home Appliance |
| 7 | Deerma | Home Appliance |
| 8 | Fans | Home Appliance |
| 9 | Garment Steam Iron | Home Appliance |
| 10 | Geyser | Home Appliance |
| 11 | Heater | Home Appliance |
| 12 | Insect Killer | Home Appliance |
| 13 | Led TV | Home Appliance |
| 14 | Microwave Oven | Home Appliance |
| 15 | Refrigerator | Home Appliance |
| 16 | Vacuum Cleaner | Home Appliance |
| 17 | Washing machine | Home Appliance |
| 18 | Water Dispenser | Home Appliance |
| 19 | Item | — (top-level) |
| 20 | Kitchen Appliances | — (top-level) |
| 21 | Air Fryer | Kitchen Appliances |
| 22 | Blender | Kitchen Appliances |
| 23 | Coffee Maker | Kitchen Appliances |
| 24 | Electric Kettle | Kitchen Appliances |
| 25 | Hotplate | Kitchen Appliances |
| 26 | Oven Toaster | Kitchen Appliances |

*All "likely, needs confirmation" parents are reasonable guesses from category naming, not verified against the real exported tree yet — but this isn't a pre-build blocker either: the Taxonomy Manager (`phase2.md` §5.2) is exactly where you confirm or correct each parent mapping, live, at any time. `needs_confirmation=true` just means "don't trust this one for a live export yet," not "stop and go check wp-admin before writing code."*

---

## 10. Batch Input Workflow

- **Bulk Entry:** Upload raw product list CSV OR quick-add individually.
- **Batch Processing:** Sequential processing.
- **Batch CSV Export:** Export Approved Only.
- **Partial Failure Handling:** Failed products stay in queue; successful products export immediately.
- **v7.0 addition — Variant Triage:** input is scanned for variant-shaped entries (same model line, multiple sizes/colors) — these are flagged to Manual Review before entering the pipeline (§2), never silently treated as one Simple product.

---

## 11. Technology Stack & Cost

- **Frontend:** Next.js (React, Tailwind CSS) — fully responsive, mobile-first. **v7.0:** mobile use case is explicitly scoped as monitoring progress and approving/rejecting flagged items on the go — not full data-entry — which keeps the mobile UI simple rather than replicating the full desktop workflow.
- **Frontend-Backend Communication:** **Server-Sent Events (SSE) / WebSockets**. The frontend will never actively poll or hang on 10s+ API requests. The backend pushes real-time progress updates to the dashboard to prevent 504 Gateway Timeouts.
- **Backend:** FastAPI (Python), LangChain/LangGraph
- **Scraping:** Playwright / Firecrawl API
- **Hosting:** DigitalOcean Droplet ($6–12/month)
- **Database:** Supabase (PostgreSQL free tier)
- **Estimated Cost:** $17–58/month hosting/DB **+ LLM API token cost (v7.0: not yet estimated — measure real per-product token usage during the 5-product pilot in §15 and extrapolate; do not treat $17–58/month as the total operating cost)**.
- **Secrets (v7.0, new):** all API keys (LLM providers, Firecrawl) stored as environment variables or in a secrets manager — never committed to any repository.
- **Content-sourcing rule (v7.0, new):** scraped competitor/official *text* is never copied verbatim into product descriptions — only facts are extracted; all prose is generated fresh by Agent 2. Avoids duplicate-content and copyright risk.

---

## 12. Critical Edge Cases & Resolutions

| Edge Case                      | Resolution                                                                                   |
| ------------------------------- | ------------------------------------------------------------------------------------------------ |
| HTML breaks CSV columns        | HTML Sanitization (`html.escape()`) + `csv` module `QUOTE_ALL`                                |
| AI invents a Brand or Category | Taxonomy Lock: AI can only select from exact live-taxonomy lists                              |
| Warranty text mismatch         | Single source of truth (matrix or override) + Agent 3 consistency check                       |
| Product Name too long          | Deterministic builder abbreviates Type until <44 chars                                        |
| Tags contain SEO keywords      | Strict 3-Tag Rule enforced by Tag Generator                                                   |
| Frontend API Timeout (504)     | Backend pushes data via SSE/WebSockets; no long-polling REST requests                         |
| Missing Images for Template A  | Dynamic Template Fallback: switches to Template B if fewer than 3 images found (v7.0 fixed threshold) |
| **(v7.0)** Scrape blocked/unreachable | Route straight to Manual Review, reason "source unreachable" — no retry, no partial-data guess |
| **(v7.0)** Sources disagree on a spec | Route to Manual Review, reason "spec conflict: [field] [value A] vs [value B]" |
| **(v7.0)** Variant-shaped input | Flagged before entering pipeline, never force-processed as Simple |
| **(v7.0)** Known out-of-stock at intake | Optional stock-status override in the input form |
| **(v7.0)** SKU collision with live catalog | Blocked at export, reason "SKU collision with live product [ID]" |
| **(v7.0)** Scraped price vs. entered price differ sharply | Warning surfaced, does not block |

---

## 13. Dashboard Features (Supabase-Powered, Mobile-Responsive)

- **Batch Input Panel**, **User Input Form** (with stock-status and warranty-override fields, v7.0), **Human Quick-QA Panel** (**Full Review Mode** with source citations / **Quick Review Mode** flagged-only, §5.7), **Manual Review Queue** (**with failure reason per item and a badge notification**, v7.0), **Template Manager**, **Taxonomy Manager**, **Price Reference Panel** (with discrepancy warnings, v7.0), **Audit Log**.
- **Real-Time Progress View:** Driven by WebSockets/SSE. Shows live agent progress without page refreshing or timing out.

---

## 14. Logging, Audit Trail & Rollback

- **Logging:** Every attempt logged, including each fact's source citation (§5.2, v7.0) for later traceability.
- **Audit Trail:** Full traceability.
- **Rollback Plan:** All products import as **Draft** (`Published = -1`).

---

## 15. Testing & Rollout Plan (v7.0: concrete acceptance criteria added — was 6 unmeasured labels)

1. **Staging Validation** — confirm a WooCommerce staging environment exists (or a Draft-only safety net on production if not); pass = one product round-trips through the full pipeline without errors.
2. **Pilot (5 Products)** — pass = 5/5 products 100% factually correct against the user's own manual re-check, 0 CSV import errors, Rank Math pre-flight score ≥ 90 on all 5, warranty consistent across all 4 locations on all 5. Any failure here blocks advancing.
3. **Staging Import Test** — actually import the pilot batch into staging (or Draft on production); pass = all 5 pages render correctly, specs table and FAQ HTML display as intended, no broken categories/tags.
4. **Scale to 20 Products** — pass = error rate stays within the same bounds as the pilot; if it degrades, stop and diagnose before scaling further.
5. **Gradual Trust Reduction** — move from Full Review Mode to Quick Review Mode only after step 4 passes cleanly; this is a one-way trust decision, not automatic.
6. **Present Results** — compare against the ~24 min/product baseline using the two separate metrics in §16.

---

## 16. Success Metrics (v7.0: split, made measurable — was conflated/vague)

| Metric               | Target               |
| --------------------- | --------------------- |
| System processing time per product (mostly unattended) | Report actual measured time from pilot — not pre-committed to a number until measured |
| **Human QA time per product** (the actual bottleneck the user cares about) | Under 5 min, measured separately from system time |
| Factual error rate   | < 1% field-level error rate, measured by spot-checking a defined % of approved products against their source citations |
| Rank Math SEO score  | 95+ consistently — confirmed via a real staging re-save, not the raw imported `Meta: rank_math_seo_score` value alone (§6.7) |
| Warranty consistency | 100% (Agent 3 hard-blocks otherwise) |

---

## 17. Complete System Flow Diagram (v7.0: extraction-failure branch added)

```
USER INPUT
    │
    ├─ Model Number (SKU)
    ├─ Regular Price / Sale Price
    ├─ Warranty (Auto-filled from Matrix, override optional)
    ├─ Stock status (default in stock, override optional)
    ├─ Template Selection (from DB)
    │
    ▼
┌─────────────────────────┐
│   AGENT 1 — EXTRACTOR   │
│  - Scrape official site  │
│  - Scrape ref sites      │
│  - Extract CITED facts   │
│    per category schema   │
│  - Never infer missing   │
│  - Check Image Count     │
└───────────┬─────────────┘
            │
      ┌─────┴──────────────────────────────┐
      │ Source unreachable / facts conflict │
      └─────────────────┬────────────────────
                         ▼
                 MANUAL REVIEW (reason attached)
            │
            ▼ (facts complete & agreed)
      ┌─────────────────┐
      │ IMAGE FALLBACK?  │
      │ If Template A    │
      │ & Images < 3:    │
      │ Switch to Temp B │
      └────────┬────────┘
               │
               ▼
┌─────────────────────────┐
│   AGENT 2 — WRITER      │
│  - Generate keywords     │
│  - Fill template JSON    │
│  - Generate SEO meta     │
│  - Generate FAQ content  │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   AGENT 3 — REVIEWER    │
│  + SEO Validator (py)    │
│  - Cross-check facts     │
│  - Warranty consistency  │
│  - SEO rules check       │
│  - Template completeness │
│  - Compute pre-flight    │
└───────────┬─────────────┘
            │
      ┌─────┴─────┐
      │ Passed?    │
      ├─ YES ──────┼──→ "Ready for QA"
      ├─ NO (writer/reviewer issue, < 3) ─┼──→ Back to Agent 2
      └─ NO (≥ 3) ─┼──→ "Manual Review Required" (reason attached)
                       │
                       ▼
              ┌─────────────────┐
              │  DETERMINISTIC   │
              │  BUILDERS        │
              │  - Product Name  │
              │  - Short Desc    │
              │  - Specs Table   │
              │  - Tags (3-Rule) │
              │  - Taxonomy Lock │
              │    (Parent>Cat)  │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  HTML SANITIZE   │
              │  (html.escape)   │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ DUPLICATE-SKU    │
              │ GUARD            │──── collision ──► MANUAL REVIEW
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  CSV ASSEMBLER   │
              │  - All 49 fields │
              │  - csv module,   │
              │    QUOTE_ALL     │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  HUMAN QA PANEL  │
              │  (Full/Quick)    │
              │  + source cites  │
              │  - Audit logged  │
              │  (SSE Push Msg)  │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  CSV EXPORT      │
              │  (Approved only) │
              │  Published = -1  │
              └─────────────────┘
```

---

## 18. Conclusion

Locks scope (including variant-input triage), fixes the verified `Categories` hierarchy bug (parent **is** prepended with `>`), defines category-specific spec schemas that were previously undefined, adds a no-hallucination/source-citation contract that actually reduces re-verification time instead of just moving it, guards against SKU collisions on a live catalog, softens SEO rules that risked keyword-stuffing penalties despite scoring well internally, and adds measurable acceptance criteria to the rollout plan. Several open items remain and are listed explicitly in §0 and §9.2 rather than guessed — this v7.0 is honest about what still needs real data from the live site before Phase 2 (build) begins.

**Verdict: Ready for Phase 0 (verification checklist above) — not yet ready for Phase 2 (code)** until the §0 checklist and §9.2's full category-parent mapping are completed against the real live site.
