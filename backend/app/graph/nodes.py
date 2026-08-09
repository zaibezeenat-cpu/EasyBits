import json
import logging
import re
from typing import Any

from app.agents.extractor import EXTRACTOR_SYSTEM_PROMPT
from app.agents.reviewer import REVIEWER_SYSTEM_PROMPT
from app.agents.writer import WRITER_SYSTEM_PROMPT
from app.builders.csv_assembler import (
    BrandCasingMismatchError,
    CategoryBreadcrumbError,
    CategoryCasingMismatchError,
    assemble_csv_row,
)
from app.builders.dimensions_builder import build_dimensions
from app.builders.html_sanitizer import strip_lsi_keyword_formatting
from app.builders.internal_links import build_link_block
from app.builders.lsi_keywords import repair_lsi_keywords

# Import builders
from app.builders.meta_description_builder import build_meta_description
from app.builders.name_builder import build_name
from app.builders.price_reference import compute_price_discrepancy
from app.builders.seo_compliance import enforce_keyword_density, ensure_lsi_in_body
from app.builders.seo_title_builder import build_seo_title
from app.builders.short_description_renderer import render_short_description
from app.builders.sku_guard import check_sku_collision
from app.builders.specs_renderer import render_specs_table
from app.builders.tag_generator import build_tags
from app.builders.title_terms import (
    harvest_title_terms,
    select_title_features,
    verify_terms,
)
from app.builders.warranty_verifier import (
    build_source_text,
    verify_warranty,
    warranty_conflict_detail,
)
from app.core.config import settings
from app.core.llm_provider import llm_provider
from app.db.repositories.brands import brands_repo
from app.db.repositories.categories import categories_repo
from app.db.repositories.manual_review import manual_review_repo
from app.db.repositories.settings import settings_repo
from app.db.repositories.sources import sources_repo
from app.db.repositories.taxonomy import taxonomy_repo
from app.db.repositories.warranty import warranty_repo
from app.graph.seo_validator import expected_meta_cta, validate_seo_rules
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult
from app.models.failure import FailureInfo
from app.models.raw_input import RawProductInput
from app.models.review_result import ReviewResult
from app.models.writer_output import WriterOutput
from app.scraping.fetcher import smart_fetch
from app.scraping.google_search_client import google_search_client
from app.scraping.orchestrator import scrape_product
from app.scraping.playwright_client import _clean_html_to_text, is_block_page
from app.scraping.source_discovery import FREE_TIERS, GOOGLE_TIER

logger = logging.getLogger(__name__)

def safe_format(template: str, **kwargs) -> str:
    """
    A safer version of .format() that only replaces known placeholders
    and doesn't get tripped up by unescaped braces in the template
    or the values.
    """
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value))
    return template

async def intake_triage(state: PipelineState) -> dict[str, Any]:
    """Validate input and detect variants."""
    raw = state.raw_input

    # Resolve category schema
    brand = await brands_repo.get_by_name(raw.brand_name)
    category = await categories_repo.get_by_name(raw.category_name)

    if not brand:
         return {
            "failure": FailureInfo(category="missing_taxonomy_match", detail=f"Brand {raw.brand_name} not found in DB."),
            "manual_review_required": True
        }

    if not category:
         return {
            "failure": FailureInfo(category="missing_taxonomy_match", detail=f"Category {raw.category_name} not found in DB."),
            "manual_review_required": True
        }

    # V8.0 Production Lock — Brand Casing Lock, enforced as early as possible too.
    if brand.name != raw.brand_name:
        return {
            "failure": FailureInfo(
                category="brand_casing_mismatch",
                detail=f"Input brand '{raw.brand_name}' does not exactly match live taxonomy casing '{brand.name}'."
            ),
            "manual_review_required": True
        }

    schema = await taxonomy_repo.get_schema_by_category(category.id)
    if not schema:
        return {
            "failure": FailureInfo(category="missing_category_schema", detail=f"No spec schema for {raw.category_name}."),
            "manual_review_required": True
        }

    # Variant detection (Phase 1 §2)
    variant_shaped = False
    if "/" in (raw.model_number or "") or " ton" in (raw.model_number or "").lower():
        variant_shaped = True

    if variant_shaped:
        return {
            "failure": FailureInfo(category="variant_shaped", detail="Variant product detected in model number."),
            "manual_review_required": True,
            "variant_shaped": True
        }

    return {
        "category_schema": schema,
        "variant_shaped": False,
        "manual_review_required": False
    }

async def _build_operator_source_docs(raw: RawProductInput) -> list[dict[str, Any]]:
    """
    Turns the operator-supplied Website Link / Details (from the real sheet) into
    authoritative source documents, in the SAME shape scrape_product produces, so
    the extractor prompt, corroboration, and the warranty cross-check all consume
    them unchanged.

    Both are optional and are combined into a SINGLE official document. When a
    link is given it is scraped directly (reusing the known-URL scraper); if that
    scrape fails (Cloudflare, 403, timeout) or returns a block page, the pasted
    details carry it rather than failing outright. The pasted details are cleaned
    and truncated with the SAME guard scraped pages use (_clean_html_to_text ->
    15k chars) so a 20k-word paste cannot blow the token budget.

    They are merged into ONE doc, not two, on purpose: two same-domain docs make
    the extractor cite every field twice with trivially different wording
    ("Westpoint" vs "WESTPOINT", "220-240V" vs "220 - 240V"), which corroboration
    then reads as a false conflict and escalates. One source -> one citation.
    """
    parts: list[str] = []
    candidate_titles: list[str] = []

    # SSRF guard: only ever fetch http(s). The operator is trusted, but this stops
    # a stray file:// / gopher:// / internal-host value from being fetched server-side.
    if raw.official_url and raw.official_url.strip().lower().startswith(("http://", "https://")):
        try:
            result = await smart_fetch(raw.official_url, raw.model_number)
            # A blocked official_url returns success=True with the anti-bot page as
            # content -- that must NOT be used. Treat a block page like a failed
            # scrape and lean on source_details instead.
            if result.success and result.content and not is_block_page(result.content):
                parts.append(result.content)
                candidate_titles = list(result.candidate_titles)
            else:
                logger.warning(
                    f"official_url {raw.official_url} was blocked or empty; "
                    f"using provided source_details if any."
                )
        except Exception as e:
            logger.warning(
                f"Scrape failed for official_url {raw.official_url}: {e}; "
                f"using provided source_details if any."
            )

    if raw.source_details and raw.source_details.strip():
        parts.append(_clean_html_to_text(raw.source_details))

    if not parts:
        return []

    return [{
        "url": raw.official_url or "operator-provided",
        "source_type": "official",
        "content": "\n\n".join(parts),
        "candidate_titles": candidate_titles,
    }]


async def extractor_node(state: PipelineState) -> dict[str, Any]:
    """Scrape and Extract facts."""
    raw = state.raw_input

    # Operator-provided source (the sheet's Website Link + Details), if any.
    operator_docs = await _build_operator_source_docs(raw)
    # provided_source_mode: "augment" (default) uses the operator source AND runs
    # discovery to cross-check; "strict" uses ONLY the operator source.
    mode = (await settings_repo.get_setting("provided_source_mode")) or "augment"

    if mode == "strict":
        # Strict: no discovery at all -- trust only what the operator supplied.
        scraped = {"scraped_data": operator_docs}
    else:
        # Augment: operator source(s) PLUS discovery. PASS 1 is FREE tiers only
        # (brand site + trusted retailers); the Google tier has a daily quota and
        # is held back to pass 2 below, so the common case stays free.
        scraped = await scrape_product(
            raw.brand_name, raw.model_number, tiers_to_run=FREE_TIERS
        )
        if "failure" in scraped and google_search_client.configured:
            logger.info("Free tiers found nothing; falling back to the Google tier.")
            scraped = await scrape_product(
                raw.brand_name, raw.model_number, tiers_to_run=GOOGLE_TIER
            )
        discovered = scraped.get("scraped_data", [])
        # Operator docs lead (top trust), then the discovered sources.
        scraped = {"scraped_data": operator_docs + discovered}

    # 2026-08-09 (owner-directed): finding literally nothing (no operator link,
    # no discovered source) no longer escalates -- it proceeds with an empty
    # source list. The Extractor's no-hallucination contract already means an
    # empty prompt yields every field UNKNOWN rather than an invented value
    # (ExtractionResult.confirmed_value returns None with zero citations,
    # exactly like a field a real source simply didn't mention), and those
    # render "Not Available" downstream instead of blocking the product. This
    # is a real accuracy trade -- a product with zero sources ships with no
    # verified specs at all -- but matches "force to find, and if not found,
    # skip; no issue" over holding the product for review.
    if not scraped["scraped_data"]:
        logger.warning(
            f"No source found (operator-provided or discovered) for "
            f"{state.raw_input.sku}; proceeding with zero grounding -- every "
            f"spec field will render 'Not Available'."
        )

    # --- Warranty cross-check (phase1.md §5.5) ---
    # The warranty is hand-typed into the input sheet and then repeated in four
    # places on the live product, so a typo there becomes a binding claim the
    # business has to honour.
    #
    # It is cross-checked against OFFICIAL brand sources ONLY, never retailers.
    # The owner sources the sheet warranty from the brand's own warranty
    # declaration (e.g. haier.com/pk), which outranks any retailer listing.
    # Retailers routinely summarise warranty differently -- the Haier pilot hit
    # a retailer stating "3 year parts" against Haier's official (and correct)
    # "1 year other parts". Cross-checking against retailers therefore
    # manufactured a conflict on a warranty that was right, and would escalate
    # essentially every product. When no official source carries the product
    # (common -- brand sites list far less than retailers), there is nothing
    # authoritative to compare against and the supplied warranty is used as-is.
    official_source_text = build_source_text(
        [d for d in scraped["scraped_data"] if d.get("source_type") == "official"]
    )
    warranty_check = verify_warranty(
        state.raw_input.warranty_override or "",
        official_source_text,
    )
    conflict = warranty_conflict_detail(warranty_check)
    if conflict:
        logger.warning(f"Warranty conflict for {state.raw_input.sku}: {conflict}")
        return {
            "failure": FailureInfo(category="warranty_conflict", detail=conflict),
            "manual_review_required": True,
        }
    if not warranty_check.checked and warranty_check.detail:
        logger.info(f"Warranty not cross-checked for {state.raw_input.sku}: {warranty_check.detail}")

    # Prepare sources for prompt
    source_docs = ""
    for idx, doc in enumerate(scraped["scraped_data"]):
        source_docs += f"### SOURCE {idx+1} [{doc['source_type']}] {doc['url']}\n{doc['content']}\n\n"

    human_prompt = f"Product: {state.raw_input.brand_name} {state.raw_input.model_number}\n\nSources:\n{source_docs}"

    try:
        extraction = await llm_provider.call(
            role="extractor",
            system_prompt=safe_format(
                EXTRACTOR_SYSTEM_PROMPT,
                category_name=state.raw_input.category_name,
                required_fields_json=json.dumps([f.key for f in state.category_schema.fields]),
                # Only the fields the schema marks inferable are shown as
                # deducible. The model is never handed a measurement here, so it
                # is never invited to guess one -- and a citation for anything
                # outside this list is discarded regardless of what it returns.
                inferable_fields_json=json.dumps(
                    [f.key for f in state.category_schema.fields if f.inferable]
                ),
                source_documents=source_docs
            ),
            human_prompt=human_prompt,
            response_model=ExtractionResult
        )

        # BUG FIX (Phase 3 integration test): after_extractor_router already
        # escalates when fields are missing/conflicting, but a router can only
        # choose a route, not set state -- so state.failure stayed None on this
        # path, and escalation_handler fell back to "other"/"Unknown error".
        # This is the single most common real-world escalation reason (a
        # source simply didn't state a required fact, or two sources
        # disagreed) -- it deserves a real reason, not a blank one.
        missing = extraction.missing_required_fields(state.category_schema)
        uncorroborated = extraction.uncorroborated_required_fields(state.category_schema)

        # PASS 2 -- only when the free sources left real gaps. Google adds more
        # independent sources so a single-source or missing field can reach
        # corroboration. Costs one extra search + extraction ONLY in this case,
        # which is why the Google quota lasts and most products stay free.
        if (missing or uncorroborated) and mode != "strict" and google_search_client.configured:
            logger.info(
                f"Corroboration incomplete after free tiers "
                f"(missing={missing}, uncorroborated={list(uncorroborated)}); "
                f"widening with the Google tier."
            )
            extra = await scrape_product(
                state.raw_input.brand_name, state.raw_input.model_number, tiers_to_run=GOOGLE_TIER
            )
            if extra.get("scraped_data"):
                combined = scraped["scraped_data"] + extra["scraped_data"]
                merged_docs = ""
                for idx, doc in enumerate(combined):
                    merged_docs += f"### SOURCE {idx+1} [{doc['source_type']}] {doc['url']}\n{doc['content']}\n\n"
                extraction = await llm_provider.call(
                    role="extractor",
                    system_prompt=safe_format(
                        EXTRACTOR_SYSTEM_PROMPT,
                        category_name=state.raw_input.category_name,
                        required_fields_json=json.dumps([f.key for f in state.category_schema.fields]),
                        inferable_fields_json=json.dumps(
                            [f.key for f in state.category_schema.fields if f.inferable]
                        ),
                        source_documents=merged_docs,
                    ),
                    human_prompt=human_prompt,
                    response_model=ExtractionResult,
                )
                scraped["scraped_data"] = combined
                missing = extraction.missing_required_fields(state.category_schema)
                uncorroborated = extraction.uncorroborated_required_fields(state.category_schema)

        # 2026-08-09 (owner-directed): a missing field (no source states it at
        # all) no longer escalates -- pass 2 above already tried harder to find
        # it; if it's still not found, it's skipped and rendered "Not Available"
        # downstream, not held for review. uncorroborated_required_fields() also
        # no longer reports "single_source" (a lone retailer now publishes, see
        # ExtractionResult.confirmed_value) -- only a genuine cross-source
        # "conflict" still blocks the product.
        conflicting = [f for f, s in uncorroborated.items() if s == "conflict"]

        # Which fields may be DEDUCED is decided by the category schema, not here.
        #
        # This replaces an earlier CORE_FIELDS bypass that filtered `missing`
        # against {"title", "brand", "regular_price", "category"}. Only "brand"
        # is a real spec-schema key -- the others are CSV columns -- so the
        # filter emptied the list almost entirely: with an official source
        # present, a product missing its model_number, wattage and voltage
        # sailed through.
        #
        # The two legitimate cases it was reaching for are both handled properly now:
        #   * field genuinely does not apply  -> required: false in the schema
        #   * field is derivable from features -> inferable: true, deduced and
        #                                         cited as confidence="inferred"
        # Both are per-category and set by the operator in the Taxonomy Manager,
        # rather than one hardcoded rule applied to every category at once.
        rejected = extraction.drop_disallowed_inferences(state.category_schema)
        if rejected:
            logger.warning(
                f"Extractor inferred value(s) for non-inferable field(s) {rejected} "
                f"on {state.raw_input.sku}; discarded. Mark the field `inferable` in "
                f"the category schema if deduction is genuinely acceptable for it."
            )
            # An inference for a field that was never allowed one may have masked a
            # real gap, so the missing/uncorroborated sets are recomputed.
            missing = extraction.missing_required_fields(state.category_schema)
            uncorroborated = extraction.uncorroborated_required_fields(state.category_schema)
            conflicting = [f for f, s in uncorroborated.items() if s == "conflict"]

        deduced = extraction.inferred_fields(state.category_schema)
        if deduced:
            logger.info(
                f"Deduced {len(deduced)} inferable field(s) for {state.raw_input.sku}: "
                f"{deduced}. Each is cited as 'inferred' and never counts as confirmed."
            )

        # 2026-08-09 (owner-directed): a missing field (no source states it at
        # all) no longer escalates -- pass 2 above already tried harder to find
        # it; if it's still not found, it's skipped and rendered "Not Available"
        # downstream, not held for review. uncorroborated_required_fields() also
        # no longer reports "single_source" (a lone retailer now publishes, see
        # ExtractionResult.confirmed_value) -- only a genuine cross-source
        # "conflict" still blocks the product. `missing` is logged for context
        # even though it no longer gates escalation.
        if missing:
            logger.info(
                f"No source stated {missing} for {state.raw_input.sku}; "
                f"proceeding, will render as 'Not Available'."
            )

        if conflicting:
            return {
                "extraction": extraction,
                "failure": FailureInfo(
                    category="spec_conflict",
                    detail=f"sources disagree on: {', '.join(conflicting)}",
                ),
                "manual_review_required": True,
            }

        return {
            "extraction": extraction,
            # Carried forward so writer_node can build the product title from
            # the wording other sellers actually use for this model.
            "competitor_titles": [
                title
                for doc in scraped["scraped_data"]
                for title in doc.get("candidate_titles", [])
            ],
            # 2026-08-09: the SAME titles, but only from source_type ==
            # "official" docs, kept separate so harvest_title_terms can trust
            # the brand's own wording without needing a second seller to
            # repeat it -- see state.py's official_titles and
            # title_terms.py's official_titles param.
            "official_titles": [
                title
                for doc in scraped["scraped_data"]
                if doc.get("source_type") == "official"
                for title in doc.get("candidate_titles", [])
            ],
        }
    except Exception as e:
        logger.error(f"Extraction failed: {e!s}", exc_info=True)
        return {
            "failure": FailureInfo(category="other", detail=f"Extraction LLM call failed: {e!s}"),
            "manual_review_required": True
        }

async def image_fallback_node(state: PipelineState) -> dict[str, Any]:
    """If < 3 images, fall back to Template B."""
    count = len(state.extraction.image_urls) if state.extraction else 0
    if count < 3:
        return {"selected_template_type": "B"}
    return {"selected_template_type": "A"}

def _extract_meta_selling_phrase(draft: str, focus_keyword: str, cta: str) -> str:
    """
    Pulls the creative middle out of the writer's meta draft so it can be
    re-assembled deterministically -- strips the focus-keyword lead, the CTA
    tail, and any warranty fragment the writer added, leaving just its angle.
    """
    text = (draft or "").strip()
    if text.lower().startswith(focus_keyword.strip().lower()):
        text = text[len(focus_keyword.strip()):]
    cta = cta.strip()
    if cta and text.rstrip().endswith(cta):
        text = text.rstrip()[: -len(cta)]
    # Drop a "Warranty: ..." fragment so it is not duplicated by the builder.
    text = re.sub(r"warranty[:\s].*", "", text, flags=re.IGNORECASE)
    return text.strip(" .,-—|")


async def writer_node(state: PipelineState) -> dict[str, Any]:
    """Generate content via Agent 2."""
    new_retry_count = state.retry_count + 1

    # Resolve warranty phrase
    brand = await brands_repo.get_by_name(state.raw_input.brand_name)
    category = await categories_repo.get_by_name(state.raw_input.category_name)
    if not brand or not category:
        # BUG FIX: brand/category are re-fetched here (and again on every Writer
        # retry) without a None-check, then `.id` was accessed unconditionally --
        # a transient DB read or a brand/category deactivated mid-run would raise
        # an unhandled AttributeError here, outside the try/except below, and
        # crash the whole pipeline.ainvoke() call instead of routing to Manual
        # Review like every other failure path in this file does.
        return {
            "failure": FailureInfo(
                category="missing_taxonomy_match",
                detail=f"Brand '{state.raw_input.brand_name}' or category '{state.raw_input.category_name}' "
                       f"could not be re-resolved in writer_node (found at intake, missing now)."
            ),
            "manual_review_required": True
        }
    # BUG FIX (Phase 3 integration test, real run): two real gaps found together.
    # (1) raw_input.warranty_override (phase1.md §5.5's explicit per-product
    #     override) was stored on every model but never actually read anywhere.
    # (2) The old fallback silently used the placeholder "Official Warranty"
    #     when warranty_matrix had no row for this brand/category -- which is
    #     every row right now, since warranty_matrix has never been seeded.
    #     That placeholder has no digits, so seo_validator.py's warranty check
    #     can never pass -- every real product would exhaust all 3 retries and
    #     land in Manual Review, every time. Worse, silently proceeding with an
    #     unverified duration is exactly the kind of fabrication the whole
    #     no-hallucination design exists to prevent. Missing warranty data is
    #     now its own explicit Manual Review reason instead of a fabricated
    #     placeholder.
    warranty_phrase = state.raw_input.warranty_override or await warranty_repo.get_phrase(brand.id, category.id)
    if not warranty_phrase:
        return {
            "failure": FailureInfo(
                category="missing_taxonomy_match",
                detail=f"No warranty phrase configured for brand '{brand.name}' / category '{category.name}' "
                       f"in the Warranty Matrix, and no per-product warranty_override was provided."
            ),
            "manual_review_required": True
        }

    # Prepare facts for prompt
    facts = {f.key: state.extraction.confirmed_value(f.key) for f in state.category_schema.fields}

    # --- V8.0 Production Lock: Product Name / Focus Keyword built FIRST, deterministically ---
    # Boss Rule title: [Brand] [Capacity] [SKU] [Series] [Features] [Full Type].
    # Series and feature wording is harvested from how OTHER sellers title this
    # exact model. 2026-08-09: a term from the brand's OWN official page
    # (state.official_titles) is trusted on its own -- e.g. "Anex ... Deluxe
    # ..." -- while a term seen only on a retailer's page (state.
    # competitor_titles) still needs to match a confirmed spec fact for this
    # product (a capability extraction never confirmed still never enters the
    # title). Everything else is dropped -- a shorter title beats an
    # unverified claim.
    # The title uses the product's REAL type, not the taxonomy category. A
    # juicer filed under "Blender" is titled "... Hard Fruit Juicer" while its
    # Categories column still reads "Kitchen Appliances > Blender" -- confirmed
    # by the owner's own exports. Using the category here produced nonsense like
    # "DWHJ-8002 Juicer Stainless Steel Blender".
    real_product_type = (
        state.extraction.confirmed_value("appliance_type")
        or state.extraction.confirmed_value("product_type")
        or state.raw_input.product_type
        or state.raw_input.category_name
    )

    harvested = harvest_title_terms(
        titles=state.competitor_titles,
        official_titles=state.official_titles,
        brand=state.raw_input.brand_name,
        model=state.raw_input.model_number,
        capacity=state.extraction.confirmed_value("capacity") or "",
        product_type=real_product_type,
    )
    verified_terms = verify_terms(
        harvested, facts, series=state.extraction.confirmed_value("series")
    )
    title_features = select_title_features(verified_terms)
    if title_features:
        logger.info(
            f"Title terms for {state.raw_input.sku}: using {title_features} "
            f"(from {len(state.competitor_titles)} competitor titles)"
        )

    # The product TITLE uses the brand's display casing ("Haier") when the owner
    # has set one; the CSV Brands column keeps the exact taxonomy term ("HAIER").
    # Falls back to the raw input casing when no display name is configured.
    title_brand = brand.title_name if brand else state.raw_input.brand_name
    product_name = build_name(
        title_brand,
        state.extraction.confirmed_value("capacity") or "",
        state.raw_input.model_number,
        real_product_type,
        features=title_features,
        series=state.extraction.confirmed_value("series"),
    )
    # Focus keyword strategy (2026-07-27, owner-directed): the PRIMARY focus
    # keyword is the SHORT, searchable brand+model (e.g. "WestPoint Pakistan
    # WF-6807"), NOT the full descriptive product name. Measured on a real
    # description, the full name sits at ~0.3% density (too low) unless unnaturally
    # repeated, while brand+model lands at a natural ~1%. The full descriptive name
    # stays the Product Name / Title; model+type becomes the 2nd keyword; LSI follow.
    model_number = state.raw_input.model_number
    focus_keyword = f"{title_brand} {model_number}".strip()
    secondary_type_keyword = f"{model_number} {real_product_type}".strip()

    meta_description_cta = expected_meta_cta(
        state.raw_input.category_name,
        capacity=state.extraction.confirmed_value("capacity"),
    )

    feedback = ""
    if state.review_result and not state.review_result.passed:
        feedback = f"\nPrevious attempt failed: {state.review_result.failure_summary}. Fix these issues."

    system_prompt = safe_format(
        WRITER_SYSTEM_PROMPT,
        cited_facts_json=json.dumps(facts),
        brand_name=state.raw_input.brand_name,
        category_name=state.raw_input.category_name,
        product_name=product_name,
        warranty_phrase=warranty_phrase,
        template_type=state.selected_template_type,
        focus_keyword=focus_keyword,
        meta_description_cta=meta_description_cta,
        feature_block_count=3 if state.selected_template_type == "A" else 2,
        reviewer_feedback_if_retry=feedback
    )

    try:
        writer_output = await llm_provider.call(
            role="writer",
            system_prompt=system_prompt,
            human_prompt="Write the content now.",
            response_model=WriterOutput
        )

        # Keep the LSI keywords tied to THIS product before anything else uses
        # them. The Writer drifts to category-level phrases ("beauty tools for
        # hair") and to unverified claims ("lightweight ..."), which waste the
        # five keyword slots Rank Math scores and assert things no source
        # confirmed. Anything not anchored to the brand, the model or a
        # CONFIRMED spec is replaced with a phrase built from those same facts.
        kept_lsi, rejected_lsi = repair_lsi_keywords(
            list(writer_output.lsi_keywords),
            brand=title_brand,
            model=state.raw_input.model_number,
            product_type=real_product_type,
            facts=facts,
        )
        if rejected_lsi:
            logger.info(
                f"LSI keywords rejected for {state.raw_input.sku} (not anchored to the "
                f"product): {rejected_lsi}; using {kept_lsi} instead."
            )
        writer_output.lsi_keywords = kept_lsi

        # Deterministic LSI guard: weave in any secondary keyword the model listed
        # but forgot to use in the body, so Rank Math's "LSI present" check passes.
        # This MUST run before density enforcement so injected keywords are counted.
        writer_output = ensure_lsi_in_body(writer_output, writer_output.lsi_keywords)
        
        # Deterministic density guard: the LLM does not reliably self-limit how
        # often it repeats the (long) focus keyword, so cap it in code -- keep the
        # first few occurrences (Rank Math needs >= 3) and replace the surplus with
        # the model number (a natural short form) so density stays under 2.5%.
        writer_output = enforce_keyword_density(
            writer_output,
            focus_keyword,
            replacement=state.raw_input.model_number,
            secondary_keyword=secondary_type_keyword,
            lsi_keywords=list(writer_output.lsi_keywords)
        )

        # SEO title stays the FULL descriptive Product Name + power word (not the
        # short focus keyword) -- the title must be descriptive, and it still
        # contains the brand+model focus keyword as a substring, so Rank Math's
        # "focus keyword in SEO title" check passes either way.
        rank_math_title = build_seo_title(
            brand=state.raw_input.brand_name,
            capacity=state.extraction.confirmed_value("capacity") or "",
            series=state.extraction.confirmed_value("series") or "",
            sku=state.raw_input.sku,
            category_name=state.raw_input.category_name,
            focus_keyword=product_name,
        )

        # The meta description is a hard character window, which LLMs cannot hit
        # reliably (the pilot produced 185 vs 150-160). So the writer's draft is
        # used only as the creative "selling angle"; the compliant string is
        # assembled deterministically to always begin with the focus keyword,
        # carry the warranty numbers, end with the exact CTA, and land in 151-155.
        selling_phrase = _extract_meta_selling_phrase(
            writer_output.rank_math_description or "", focus_keyword, meta_description_cta
        )
        try:
            writer_output.rank_math_description = build_meta_description(
                focus_keyword=focus_keyword,
                warranty_phrase=warranty_phrase,
                cta=meta_description_cta,
                selling_phrase=selling_phrase,
            )
        except ValueError as e:
            # Unbuildable = the product name itself is too long to leave room for
            # a compliant meta. Surface it rather than shipping a malformed one.
            return {
                "failure": FailureInfo(category="production_lock_violation", detail=str(e)),
                "manual_review_required": True,
            }

        return {
            "writer_output": writer_output,
            "retry_count": new_retry_count,
            "resolved_warranty_phrase": warranty_phrase,
            "name": product_name,
            "rank_math_focus_keyword": focus_keyword,
            "rank_math_secondary_keyword": secondary_type_keyword,
            "rank_math_title": rank_math_title,
            "meta_description_cta": meta_description_cta,
        }
    except Exception as e:
        logger.error(f"Writer failed: {e!s}", exc_info=True)
        return {
            "failure": FailureInfo(category="other", detail=f"Writer LLM call failed: {e!s}"),
            "manual_review_required": True
        }

async def reviewer_node(state: PipelineState) -> dict[str, Any]:
    """SEO and Fact Check via Agent 3."""
    focus_keyword = state.rank_math_focus_keyword or state.name or f"{state.raw_input.brand_name} {state.raw_input.model_number}"

    # Concatenate writer output for review as per prompt instructions
    w = state.writer_output
    concatenated_content = f"{w.hero_heading}\n{w.hero_paragraph}\n"
    concatenated_content += "\n".join(w.feature_texts) + "\n"
    concatenated_content += "\n".join(w.features_bullets) + "\n"
    concatenated_content += "\n".join([faq.answer for faq in w.faqs])

    # 1. Deterministic SEO Checks (V8.0 Production Lock rules)
    # expected_cta reuses the EXACT string writer_node already resolved (with the
    # real capacity baked in) — never recomputed here, so a 2.0 Ton unit can never
    # be silently validated against a "1.5 ton" (or any other mismatched) claim.
    seo_checks = validate_seo_rules(
        writer_output=w,
        focus_keyword=focus_keyword,
        product_name=state.name or "",
        concatenated_content=concatenated_content,
        rank_math_title=state.rank_math_title or "",
        warranty_phrase=state.resolved_warranty_phrase or "",
        category_name=state.raw_input.category_name,
        expected_cta=state.meta_description_cta or "",
        secondary_keyword=state.rank_math_secondary_keyword or "",
    )

    # 2. Warranty Consistency Check (Phase 1 §5.5)
    w_phrase = state.resolved_warranty_phrase or ""

    # FAQ Q5 check
    faq_warranty = w.faqs[4].answer
    faq_match = w_phrase.lower() in faq_warranty.lower()

    warranty_consistent = faq_match

    # 3. Semantic Fact Check via LLM
    facts = {f.key: state.extraction.confirmed_value(f.key) for f in state.category_schema.fields}

    # The warranty is an authoritative fact from the operator's sheet, NOT from
    # the scraped extraction, so it is absent from `facts`. Without this, the
    # reviewer flags the warranty the writer was REQUIRED to include as an
    # unsupported claim -- the exact false "warranty claims not in ground truth"
    # failure the Haier pilot hit. Adding it tells the reviewer the warranty is
    # confirmed ground truth.
    if state.resolved_warranty_phrase:
        facts["warranty"] = state.resolved_warranty_phrase

    system_prompt = safe_format(
        REVIEWER_SYSTEM_PROMPT,
        cited_facts_json=json.dumps(facts),
        writer_output_text=concatenated_content
    )

    try:
        review_result = await llm_provider.call(
            role="reviewer",
            system_prompt=system_prompt,
            human_prompt="Review the content.",
            response_model=ReviewResult
        )

        # Combine SEO checks
        review_result.checks = seo_checks
        review_result.warranty_consistent = warranty_consistent

        all_passed = review_result.passed and all(c.passed for c in seo_checks) and warranty_consistent

        # Update failure summary if any failed
        if not all_passed:
            failed_seo = [c.detail for c in seo_checks if not c.passed]
            if not warranty_consistent:
                failed_seo.append(f"Warranty inconsistency detected. Phrase '{w_phrase}' not found in all locations.")

            review_result.failure_summary = (review_result.failure_summary or "") + " " + "; ".join(failed_seo)
            review_result.passed = False

        result: dict[str, Any] = {"review_result": review_result}

        # 2026-08-09 (owner-directed): retry exhaustion no longer escalates --
        # after_review_router now sends it to "builders" regardless of
        # `passed` once retry_count reaches MAX_WRITER_REVIEWER_ATTEMPTS
        # (raised from a hardcoded 3, see that setting's docstring).
        # review_result (with its per-check pass/fail detail) is still
        # returned and persisted on the product row -- and surfaced as a
        # visible badge on the Products page and product detail page -- so
        # the reason a product didn't cleanly pass every SEO/fact check stays
        # visible; it just no longer blocks the CSV from being produced.
        if not all_passed and state.retry_count >= settings.MAX_WRITER_REVIEWER_ATTEMPTS:
            logger.warning(
                f"Writer/Reviewer exhausted {settings.MAX_WRITER_REVIEWER_ATTEMPTS} attempts "
                f"for {state.raw_input.sku} without passing every check ({review_result.failure_summary}); "
                f"shipping the last attempt rather than escalating."
            )

        return result
    except Exception as e:
        logger.error(f"Reviewer failed: {e!s}", exc_info=True)
        return {
            "failure": FailureInfo(category="other", detail=f"Reviewer LLM call failed: {e!s}"),
            "manual_review_required": True
        }

async def escalation_handler(state: PipelineState) -> dict[str, Any]:
    """Logs failure and escalates."""
    await manual_review_repo.add(
        product_id=str(state.product_id),
        batch_id=str(state.batch_id),
        reason_code=state.failure.category if state.failure else "other",
        reason_detail=state.failure.detail if state.failure else "Unknown error"
    )
    return {"manual_review_required": True}

async def deterministic_builders_node(state: PipelineState) -> dict[str, Any]:
    """Runs all code-based builders."""
    import html

    # Sanitize AI output before rendering.
    # V8.0 Production Lock ordering: strip LSI/focus-keyword wrapper tags FIRST
    # (Zero Tolerance rule — Rank Math must see plain text), THEN html.escape().
    wo = state.writer_output.model_copy(deep=True)

    keywords_to_unwrap = list(wo.lsi_keywords) + [state.rank_math_focus_keyword or state.name or ""]

    def unwrap_and_escape(text: str) -> str:
        text = strip_lsi_keyword_formatting(text, keywords_to_unwrap)
        return html.escape(text)

    wo.hero_heading = unwrap_and_escape(wo.hero_heading)
    wo.hero_paragraph = unwrap_and_escape(wo.hero_paragraph)
    wo.feature_headings = [unwrap_and_escape(h) for h in wo.feature_headings]
    wo.feature_texts = [unwrap_and_escape(t) for t in wo.feature_texts]
    wo.features_bullets = [unwrap_and_escape(b) for b in wo.features_bullets]
    for faq in wo.faqs:
        faq.question = unwrap_and_escape(faq.question)
        faq.answer = unwrap_and_escape(faq.answer)

    name = state.name or build_name(
        state.raw_input.brand_name,
        state.extraction.confirmed_value("capacity") or "",
        state.raw_input.model_number,
        state.raw_input.category_name
    )

    tags = build_tags(state.raw_input.brand_name, state.raw_input.category_name)

    specs_html = render_specs_table(
        state.extraction,
        state.category_schema,
        state.resolved_warranty_phrase or "Official Warranty"
    )

    dims = build_dimensions(state.extraction)

    # Price discrepancy warning (phase1.md §9.1's price-reference system): flags
    # a large gap between the user's entered price and the scraped official
    # price without blocking entry -- may catch a typo or a stale scrape. This
    # was imported but never called anywhere in the pipeline until now.
    price_discrepancy_pct = compute_price_discrepancy(
        state.extraction.scraped_official_price if state.extraction else None,
        state.raw_input.regular_price,
    )

    # Render descriptions using sanitized AI output
    short_description = render_short_description(
        wo,
        name,
        state.raw_input.category_name,
        state.resolved_warranty_phrase or "Official Warranty"
    )

    # Both templates render deterministically in the store's WoodMart theme:
    # Template A uses the hardcoded zig-zag image grid; Template B (no images)
    # uses the styled two-section + spec-box + FAQ-accordion layout the owner uses.
    if state.selected_template_type == "A":
        from app.builders.description_merger import merge_description_template_a
        description = merge_description_template_a(wo, name)
    else:
        from app.builders.description_merger import render_template_b
        description = render_template_b(wo, name, focus_keyword=state.rank_math_focus_keyword or "")

    # Rank Math requires an internal link, an external link, and that the
    # external one be dofollow. The category and brand archives are genuinely
    # useful navigation, and the manufacturer's site is a real trust signal.
    # A brand with no official site on record simply gets no external link.
    official_sites = await sources_repo.get_brand_aliases(state.raw_input.brand_name)
    category = await categories_repo.get_by_name(state.raw_input.category_name)
    parent_name = None
    if category and category.parent_id:
        parent = await categories_repo.get(category.parent_id)
        parent_name = parent.name if parent else None

    link_block = build_link_block(
        brand_name=state.raw_input.brand_name,
        category_name=state.raw_input.category_name,
        parent_category=parent_name,
        official_brand_domain=official_sites[0] if official_sites else None,
    )
    if link_block:
        description = description + link_block

    return {
        "name": name,
        "tags": tags,
        "specs_table_html": specs_html,
        "dimensions": dims,
        "short_description": short_description,
        "description": description,
        "price_discrepancy_pct": price_discrepancy_pct,
    }

async def html_sanitize_node(state: PipelineState) -> dict[str, Any]:
    """
    Pass-through node. LSI-unwrapping + html.escape() now happen in
    deterministic_builders_node before template merging so tag-stripping still
    has real HTML structure to match against, and to preserve intentional HTML
    tags in the merged template.
    """
    return {}

async def duplicate_sku_guard_node(state: PipelineState) -> dict[str, Any]:
    """Check for SKU collisions."""
    is_duplicate = await check_sku_collision(state.raw_input.sku)
    if is_duplicate:
        return {
            "failure": FailureInfo(category="sku_collision", detail=f"SKU {state.raw_input.sku} already exists in WooCommerce snapshot."),
            "manual_review_required": True
        }
    return {}

async def csv_row_assembler_node(state: PipelineState) -> dict[str, Any]:
    """Assemble final 49-column row."""
    # V8.0 Production Lock: Categories must be "[Parent] > [Category]"; resolve
    # the real parent from taxonomy instead of using the bare category name.
    # The breadcrumb is built ONLY from live taxonomy. An earlier version fell
    # back to `state.raw_input.category_name` when the lookup failed, which let
    # an unverified operator-typed value reach the CSV -- and a wrong-cased term
    # creates a duplicate category in the live WooCommerce store rather than
    # filing under the existing one. `None` here means "unverified", and the
    # Category Casing Lock in the assembler turns that into an escalation.
    category = await categories_repo.get_by_name(state.raw_input.category_name)
    canonical_category_path = None
    if category:
        if category.parent_id:
            parent = await categories_repo.get(category.parent_id)
            if parent:
                canonical_category_path = f"{parent.name} > {category.name}"
        else:
            # A legitimate TOP-LEVEL category (e.g. "Beauty") -- its breadcrumb is
            # just its own name. Setting it here (rather than leaving None) marks it
            # verified so the assembler's casing lock passes instead of rejecting it.
            canonical_category_path = category.name

    brand = await brands_repo.get_by_name(state.raw_input.brand_name)
    canonical_brand_name = brand.name if brand else None

    try:
        row = assemble_csv_row(
            state,
            canonical_category_path or state.raw_input.category_name,
            state.raw_input.brand_name,
            canonical_brand_name=canonical_brand_name,
            canonical_category_path=canonical_category_path,
        )
    except (BrandCasingMismatchError, CategoryBreadcrumbError, CategoryCasingMismatchError) as e:
        return {
            "failure": FailureInfo(category="production_lock_violation", detail=str(e)),
            "manual_review_required": True
        }

    return {"csv_row": row}
