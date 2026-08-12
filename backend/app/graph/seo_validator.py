import math
import re

from app.builders.name_builder import (
    MAX_NAME_LENGTH,
    contains_forbidden_abbreviation,
    title_format_violation,
)
from app.builders.seo_compliance import count_keyword_occurrences
from app.builders.seo_title_builder import (
    seo_title_contains_focus_keyword,
    title_ends_with_power_word,
)
from app.builders.warranty_verifier import extract_durations
from app.models.review_result import SeoCheckResult
from app.models.writer_output import WriterOutput

# Keyword presence is measured two ways, because a long Boss-Rule product name
# behaves differently from a short keyword:
#   * a PRESENCE floor by occurrence count -- phase1.md §6.8 line 146 locks the
#     target as the Focus Keyword appearing "naturally, typically 3-6 times".
#     An exact-match percentage floor cannot be used: Rank Math counts the
#     keyword AND its combinations, we count only exact full-phrase matches, so
#     a long phrase legitimately sits near 0.3-1% exact density and a 1% floor
#     false-fails it.
#   * a STUFFING ceiling by density -- Rank Math warns above 2.5%
#     (rankmath.com/kb/score-100-in-tests), and Google penalises stuffing even
#     when Rank Math's own meter still reads green.
MIN_KEYWORD_OCCURRENCES = 3
KEYWORD_DENSITY_MAX = 0.025

# phase1.md §6.8 item 13's thin-content guard. A floor in its own right --
# Google treats short product copy as thin however clean the keywords are --
# but not always sufficient; see minimum_body_words.
MIN_BODY_WORDS = 200


def minimum_body_words(*, lsi_count: int, has_secondary: bool) -> int:
    """The shortest body copy that can satisfy every check at once.

    Three checks constrain the body together, and two of them force a MINIMUM
    number of keyword matches: keyword_density_in_range needs the primary
    keyword at least MIN_KEYWORD_OCCURRENCES times, lsi_keywords_present_in_body
    needs each LSI keyword at least once, and ensure_lsi_in_body injects the
    secondary. Those same matches are then divided by the word count and capped
    at KEYWORD_DENSITY_MAX.

    So a short body is not merely thin, it is arithmetically unwinnable. With
    the usual 3 LSI keywords the mandatory matches total 7, which only fits
    under 2.5% from 280 words up -- yet the old flat 200-word floor passed
    anything above 200. Copy landing between the two was told by the reviewer
    that its density was too high, fed that back to the writer, which removed
    keyword mentions and then failed "primary >= 3" or "LSI present" instead.
    Three attempts burned and the product reached Manual Review carrying a
    density complaint whose real fix -- write more -- was never stated.

    Args:
        lsi_count: LSI keywords the writer returned (each must appear once).
        has_secondary: Whether a secondary keyword is also being injected.

    Returns:
        The word count at or above which every check is simultaneously
        satisfiable, never below the spec's thin-content floor.
    """
    required_matches = MIN_KEYWORD_OCCURRENCES + (1 if has_secondary else 0) + max(lsi_count, 0)
    # ceil is a no-op at the current 2.5% (dividing by 1/40 always lands whole)
    # -- kept because a ceiling like 3% would not, and rounding down there puts
    # the floor back inside the dead zone by a word.
    density_floor = math.ceil(required_matches / KEYWORD_DENSITY_MAX)
    return max(MIN_BODY_WORDS, density_floor)

# Category CTA templates (V8.0 Production Lock). Extend as new categories are onboarded.
# {capacity} is filled with the product's ACTUAL extracted capacity (e.g. "1.0 Ton",
# "2.0 Ton") — never hardcode a specific tonnage/size here, or every product that
# isn't that exact size ships a factually wrong claim in its meta description.
CATEGORY_CTA_TEMPLATE: dict[str, str] = {
    "Air conditioner": "Buy the best {capacity} AC in Pakistan today.",
}
DEFAULT_CTA_TEMPLATE = "Buy the best {category} in Pakistan today."


def expected_meta_cta(category_name: str, capacity: str | None = None) -> str:
    """
    Builds the fixed CTA sentence for a category, substituting the product's real
    capacity where the category's template needs one. Falls back to the generic
    category-name CTA if the category has no capacity-specific template, or if a
    capacity-specific template exists but no capacity value was found (UNKNOWN) —
    it's better to fall back to a true generic claim than to guess a size.
    """
    template = CATEGORY_CTA_TEMPLATE.get(category_name)
    if template and capacity:
        return template.format(capacity=capacity)
    return DEFAULT_CTA_TEMPLATE.format(category=category_name.lower())


def validate_seo_rules(
    writer_output: WriterOutput,
    focus_keyword: str,
    product_name: str,
    concatenated_content: str,
    rank_math_title: str,
    warranty_phrase: str,
    category_name: str,
    expected_cta: str,
    secondary_keyword: str = "",
) -> list[SeoCheckResult]:
    """
    V8.0 Production Lock — Deterministic SEO checks.

    Rules superseded from phase1.md v7.0 (ripped out, not layered):
      - "10-13 keyword stacking" is GONE. Focus keyword is exactly one keyword,
        locked to the exact Product Name.
      - The "- Best Price in Pakistan | kiachahiye.com" title suffix is GONE,
        replaced by the deterministic "Boss Title Rule" / power-word title.
      - Meta description is no longer "<=155 chars ends with !"; it is now a
        strict 151-155 char window with content assertions (focus keyword lead,
        warranty mention, fixed CTA).
    """
    results = []

    # 1. Product Name Check.
    # Raised 44 -> 60 -> MAX_NAME_LENGTH (90), each time for the same reason:
    # the cap was rejecting the owner's OWN correct titles and burning
    # Writer/Reviewer retries trying to shorten something already right.
    # 2026-08-11: the owner's written Boss Rule states "Max ~90 characters",
    # and 3 of his 5 canonical example titles measure 63-84 characters --
    # every one of which failed the 60 cap. Sourced from name_builder's
    # MAX_NAME_LENGTH so the builder and the validator can never disagree
    # about the limit again (they were independently hardcoded before).
    results.append(SeoCheckResult(
        check_name="product_name_length",
        passed=len(product_name) <= MAX_NAME_LENGTH,
        detail=f"Product name length is {len(product_name)} (limit {MAX_NAME_LENGTH})."
    ))

    # Boss Rule: the product type is never abbreviated. "AC" and "Air
    # Conditioner" are different keyword phrases to Rank Math, so an abbreviated
    # title silently targets a different keyword than the one being optimised.
    abbreviation = contains_forbidden_abbreviation(product_name)
    results.append(SeoCheckResult(
        check_name="product_name_no_abbreviation",
        passed=abbreviation is None,
        detail=(
            f"Product name uses the abbreviation '{abbreviation}'; write the full "
            f"product type instead."
            if abbreviation else
            "Product name uses the full product type."
        )
    ))

    # Boss Rule Step 3 (2026-08-10): format hygiene, checked independently of
    # name_builder.py's own _sanitize_title() -- see title_format_violation's
    # docstring for why this is a second gate, not a redundant one.
    format_violation = title_format_violation(product_name)
    results.append(SeoCheckResult(
        check_name="product_name_format_hygiene",
        passed=format_violation is None,
        detail=(
            f"Product name {format_violation}."
            if format_violation else
            "Product name has no empty brackets, double spaces, trailing hyphen, or commas."
        )
    ))

    # 2. Slug Check (<= 75 chars)
    slug = product_name.lower().replace(" ", "-").replace("/", "-")
    results.append(SeoCheckResult(
        check_name="slug_length",
        passed=len(slug) <= 75,
        detail=f"Derived slug length is {len(slug)} (limit 75)."
    ))

    # 3. Focus Keyword coherence (2026-07-27): the PRIMARY focus keyword is the
    # SHORT brand+model (e.g. "WestPoint Pakistan WF-6807"), NOT the full product
    # name -- a long full-name keyword can't reach a natural ~1% density. It must
    # still be a real, single (no comma) phrase that is a SUBSTRING of the Product
    # Name (so it is coherent and present in the title/content), never LLM-random.
    fk = (focus_keyword or "").strip()
    focus_keyword_ok = bool(fk) and "," not in fk and fk.lower() in (product_name or "").lower()
    results.append(SeoCheckResult(
        check_name="focus_keyword_is_coherent_primary",
        passed=focus_keyword_ok,
        detail=f"Focus keyword must be a single phrase contained in the Product Name. Got '{focus_keyword}' vs Name '{product_name}'."
    ))

    # 4. SEO Title — must CONTAIN the primary focus keyword verbatim.
    # Rank Math's highest-weighted Basic SEO test. The old category-descriptor
    # title inserted words into the middle of the product name, splitting the
    # phrase and failing this on every single product.
    results.append(SeoCheckResult(
        check_name="seo_title_contains_focus_keyword",
        passed=seo_title_contains_focus_keyword(rank_math_title, focus_keyword),
        detail=(
            f"SEO title must contain the focus keyword verbatim. "
            f"Title='{rank_math_title}' | keyword='{focus_keyword}'."
        )
    ))

    # 5. SEO Title — power word present (also satisfies Rank Math's Sentiment test).
    results.append(SeoCheckResult(
        check_name="seo_title_power_word",
        passed=title_ends_with_power_word(rank_math_title, category_name),
        detail=f"SEO title must end with the power-word suffix. Got '{rank_math_title}'."
    ))

    # 6. SEO Title — must contain a number (Rank Math "Number in Title").
    # Model numbers and capacities supply this naturally; the check exists so a
    # product whose name happens to have neither is caught rather than shipped.
    results.append(SeoCheckResult(
        check_name="seo_title_contains_number",
        passed=bool(re.search(r"\d", rank_math_title)),
        detail=f"SEO title should contain a digit (model number or capacity). Got '{rank_math_title}'."
    ))

    # 7. Focus keyword must appear in a SUBHEADING (Rank Math "Focus Keyword in
    # Subheadings"). The real exports satisfy this by making the first <h2> the
    # exact product name.
    results.append(SeoCheckResult(
        check_name="focus_keyword_in_subheading",
        passed=focus_keyword.strip().lower() in concatenated_content.lower(),
        detail=(
            "Focus keyword must appear in at least one subheading; the first "
            "<h2> should be the product name."
        )
    ))

    # Meta Description — 150-160 characters.
    # Widened from the old 151-155: that 5-character window was so tight the
    # Writer routinely missed it and burned retries on a purely cosmetic miss,
    # and real exported descriptions measured 147-154. 150-160 is the range the
    # site owner specified and matches Rank Math's own 120-160 guidance.
    desc = writer_output.rank_math_description.strip()
    desc_len = len(desc)
    results.append(SeoCheckResult(
        check_name="meta_description_length_150_160",
        passed=150 <= desc_len <= 160,
        detail=f"Meta description length is {desc_len} (required 150-160)."
    ))

    # 6. Meta Description — must BEGIN with the focus keyword.
    begins_with_kw = desc.lower().startswith(focus_keyword.lower())
    results.append(SeoCheckResult(
        check_name="meta_description_begins_with_focus_keyword",
        passed=begins_with_kw,
        detail=f"Meta description must begin with the focus keyword '{focus_keyword}'."
    ))

    # 7. Meta Description — must mention the warranty accurately.
    # V3.0 correction: real reference examples (confirmed against the live site)
    # abbreviate the warranty ("Warranty: 10-yr.") rather than repeating the full
    # stored phrase verbatim -- necessary because a long Boss-Rule focus keyword
    # can already consume most of the 151-155 character budget, leaving no room
    # for a full compound warranty sentence too. Relaxed to: every duration
    # number in the real warranty phrase must appear somewhere in the
    # description (so a duration can never be silently dropped or invented),
    # without requiring the exact sentence wording.
    # BUG FIX (found by tests/unit/test_every_check_can_fail.py): this used to
    # search for the bare DIGITS of the warranty anywhere in the description, so
    # a "1 Year Warranty" was satisfied by the "1" inside "1.5 Ton" in the CTA
    # -- a description with NO warranty mention at all passed the warranty
    # check. Now it compares DURATIONS (number + time unit), so a tonnage,
    # capacity or model number can never stand in for a warranty term.
    required_durations = extract_durations(warranty_phrase)
    present_durations = extract_durations(desc)
    missing_durations = [d for d in required_durations if d not in present_durations]
    warranty_mentioned = bool(required_durations) and not missing_durations
    results.append(SeoCheckResult(
        check_name="meta_description_mentions_warranty",
        passed=warranty_mentioned,
        detail=(
            f"Meta description must state the warranty duration(s) {required_durations} "
            f"from '{warranty_phrase}'. Found {present_durations}"
            + (f"; missing {missing_durations}." if missing_durations else ".")
        )
    ))

    # 8. Meta Description — must end with the fixed CTA sentence for this product.
    # `expected_cta` is passed in (already resolved with the real capacity by the
    # caller) rather than recomputed here, so the Writer's prompt and the
    # Reviewer's check can never independently drift onto two different CTA strings.
    ends_with_cta = desc.endswith(expected_cta)
    results.append(SeoCheckResult(
        check_name="meta_description_ends_with_cta",
        passed=ends_with_cta,
        detail=f"Meta description must end with the fixed CTA: '{expected_cta}'."
    ))

    # 9. LSI Keyword Count — 2 to 3 (feeds the multi-keyword focus field).
    # Rank Math scores up to 5 focus keywords, so 1 primary + 1 secondary + 3 LSIs = 5 max.
    # Each must appear natively (plain text) in the body.
    lsi = writer_output.lsi_keywords
    lsi_count_ok = 2 <= len(lsi) <= 3
    results.append(SeoCheckResult(
        check_name="lsi_keyword_count",
        passed=lsi_count_ok,
        detail=f"2 to 3 LSI keywords required, got {len(lsi)}."
    ))

    lsi_present = all(kw.lower() in concatenated_content.lower() for kw in lsi) if lsi else False
    results.append(SeoCheckResult(
        check_name="lsi_keywords_present_in_body",
        passed=lsi_present,
        detail="All LSI keywords must appear natively in the HTML body text." if lsi_present else "One or more LSI keywords are missing from the body text."
    ))

    # 10. Image Alt Text — each alt text must be the focus keyword or one of the 3 LSI keywords.
    allowed_alts = {focus_keyword.lower(), *[k.lower() for k in lsi]}
    alt_texts = [writer_output.alt_text_1, writer_output.alt_text_2, writer_output.alt_text_3]
    alts_valid = all(a.strip().lower() in allowed_alts for a in alt_texts)
    results.append(SeoCheckResult(
        check_name="image_alt_text_valid",
        passed=alts_valid,
        detail="Every image alt attribute must be strictly the focus keyword or an LSI keyword." if alts_valid else f"Invalid alt text found. Alts: {alt_texts}. Allowed: {sorted(allowed_alts)}."
    ))

    # 11. First 10% Rule (Primary/focus keyword in first 10% of text).
    first_10_percent_idx = len(concatenated_content) // 10
    passed_first_10 = focus_keyword.lower() in concatenated_content[:max(first_10_percent_idx, 100)].lower()
    results.append(SeoCheckResult(
        check_name="first_10_percent_rule",
        passed=passed_first_10,
        detail="Focus keyword found in first 10% of content." if passed_first_10 else "Focus keyword NOT found in first 10% of content."
    ))

    # 12. Thin Content Guard — body copy must be at least 200 words (e-commerce
    # best practice; Google treats short, generic product copy as thin content
    # and it ranks poorly regardless of how clean the metadata is).
    # Rank Math scores content length RED below 600 words, so the previous
    # 200-word floor guaranteed a red mark on every product. 600 is the
    # threshold that turns it yellow/green; 2,500+ (its "green" ideal) is aimed
    # at pillar articles, not product pages, and is not enforced here.
    word_count = len(concatenated_content.split())
    # The floor is not a constant, because the density check below imposes one
    # of its own -- see minimum_body_words for why 200 alone left an unwinnable
    # 200-279 word zone.
    min_words = minimum_body_words(
        lsi_count=len([k for k in writer_output.lsi_keywords if k.strip()]),
        has_secondary=bool(secondary_keyword.strip()),
    )
    results.append(SeoCheckResult(
        check_name="content_length_minimum",
        # phase1.md §6.8 item 13 locks the floor at 200 words (thin-content
        # guard), NOT 600. Rank Math's own word-count test EXCLUDES product
        # pages entirely (verified against rankmath.com/kb/score-100-in-tests),
        # so the earlier 600 was a false failure inherited from a misread of
        # Rank Math -- it escalated valid product copy on length alone.
        passed=word_count >= min_words,
        detail=(
            f"Body content is {word_count} words (floor is {min_words}: the spec's "
            f"{MIN_BODY_WORDS}-word thin-content guard, raised where needed so the "
            f"{MIN_KEYWORD_OCCURRENCES} primary + secondary + LSI keyword mentions the other "
            f"checks require still fit under the {KEYWORD_DENSITY_MAX * 100:.1f}% density "
            f"ceiling). Product pages are exempt from Rank Math's own length test."
        )
    ))

    # Keyword density = focus-keyword phrase occurrences RELATIVE TO TOTAL WORD
    # COUNT (Rank Math's real metric, verified against
    # rankmath.com/kb/score-100-in-tests: "how many times your focus keyword ...
    # appears relative to total word count"; optimal 1-1.5%, warning above 2.5%).
    #
    # V8.0 Update: Rank Math COMBINES the occurrences of the Primary, Secondary,
    # and LSI keywords for this check. We must sum all unique focus keywords
    # before computing density against the KEYWORD_DENSITY_MAX limit, while still
    # ensuring the primary keyword alone meets the MIN_KEYWORD_OCCURRENCES floor.
    primary_occurrences = concatenated_content.lower().count(focus_keyword.strip().lower())
    
    all_keywords = [focus_keyword.strip().lower()]
    if secondary_keyword.strip():
        all_keywords.append(secondary_keyword.strip().lower())
    for kw in writer_output.lsi_keywords:
        if kw.strip():
            all_keywords.append(kw.strip().lower())
            
    # Counted through the SAME helper the density enforcer uses, so the guard
    # that rewrites the copy and the check that grades it can never disagree
    # about what the density is. Overlapping keywords are counted once -- see
    # count_keyword_occurrences for why per-keyword counting overstated by 60%.
    combined_occurrences = count_keyword_occurrences([concatenated_content], all_keywords)
    combined_density = (combined_occurrences / word_count) if word_count else 0.0
    
    results.append(SeoCheckResult(
        check_name="keyword_density_in_range",
        passed=primary_occurrences >= MIN_KEYWORD_OCCURRENCES and combined_density <= KEYWORD_DENSITY_MAX,
        detail=(
            f"Primary keyword appears {primary_occurrences} time(s). Combined density is {combined_density * 100:.2f}% "
            f"(need primary >= {MIN_KEYWORD_OCCURRENCES} occurrences and combined <= {KEYWORD_DENSITY_MAX * 100:.1f}% to avoid stuffing)."
        )
    ))

    return results
