"""
Proves every SEO check is capable of FAILING.

WHY THIS FILE EXISTS
--------------------
A check that silently always returns True is worse than no check at all: it
gives false confidence, the test suite stays green, and a broken product ships
to the live store. Tests that only assert "the good input passes" cannot detect
this -- a check hardcoded to `passed=True` passes them too.

So for every check the validator emits, this file feeds input that SHOULD fail
it and asserts it actually does. If someone later breaks a check's logic so it
can never fail, the corresponding test here goes red.

The final test is the important one: it enumerates the checks the validator
actually produces and fails if any of them has no failure test here. That way a
NEWLY ADDED check cannot quietly ship without a proof that it can fail.
"""

import pytest

from app.graph.seo_validator import expected_meta_cta, validate_seo_rules
from app.models.writer_output import FAQPair, WriterOutput

KEYWORD = "Dawlance DW-131 Inverter Air Conditioner"
WARRANTY = "1 Year Brand Warranty"
CTA = expected_meta_cta("Air conditioner", capacity="1.5 Ton")
TITLE = f"{KEYWORD} | Buy Smart"


LSI = ["inverter cooling", "energy saving system", "split ac pakistan"]


def _body(mentions: int = 3, words: int = 640) -> str:
    """
    Body copy with a controllable keyword count and length.

    Defaults are tuned to land inside every check at once: comfortably over the
    200-word floor, the focus keyword present the spec's minimum 3 times (>=3
    occurrences and <= 2.5% density), and all three LSI phrases present.
    """
    filler = ("This unit is built for demanding conditions and long daily use "
              "with dependable components throughout the season. ")
    lsi_text = " ".join(LSI) + ". "
    repeats = max(words // 18, 1)
    return (f"{KEYWORD} " * mentions) + lsi_text + (filler * repeats)


def _writer(**overrides) -> WriterOutput:
    base = {
        "hero_heading": "Heading",
        "hero_paragraph": _body(),
        "feature_headings": ["A", "B", "C"],
        "feature_texts": [_body(1), _body(1), _body(1)],
        "features_bullets": ["one", "two", "three", "four"],
        "faqs": [
            FAQPair(question="Q1", answer="A1"),
            FAQPair(question="Q2", answer="A2"),
            FAQPair(question="Q3", answer="A3"),
            FAQPair(question="Q4", answer="A4"),
            FAQPair(question="What is the official warranty?",
                    answer=f"It comes with a {WARRANTY} provided by Dawlance."),
        ],
        "short_desc_feature_1": "a", "short_desc_feature_2": "b", "short_desc_feature_3": "c",
        "rank_math_description": _good_description(),
        "lsi_keywords": list(LSI),
        "alt_text_1": KEYWORD, "alt_text_2": LSI[0], "alt_text_3": LSI[1],
    }
    base.update(overrides)
    return WriterOutput(**base)


def _good_description() -> str:
    """
    A description satisfying length, keyword lead, warranty and CTA at once.
    Padded one word at a time so it lands inside the 150-160 window rather than
    overshooting it.
    """
    head = f"{KEYWORD} includes a {WARRANTY}"
    padding = ["and", "dependable", "everyday", "cooling", "for", "your", "home",
               "through", "the", "long", "summer", "season", "ahead"]
    for word in padding:
        if len(f"{head}. {CTA}") >= 150:
            break
        head = f"{head} {word}"
    return f"{head}. {CTA}"


def _run(writer=None, keyword=KEYWORD, name=KEYWORD, content=None, title=TITLE,
         warranty=WARRANTY, cta=CTA):
    return {
        c.check_name: c
        for c in validate_seo_rules(
            writer_output=writer or _writer(),
            focus_keyword=keyword,
            product_name=name,
            concatenated_content=content if content is not None else _body(),
            rank_math_title=title,
            warranty_phrase=warranty,
            category_name="Air conditioner",
            expected_cta=cta,
        )
    }


# --- One failing case per check ---------------------------------------------

def test_product_name_length_can_fail():
    assert not _run(name="X" * 200)["product_name_length"].passed


def test_product_name_no_abbreviation_can_fail():
    assert not _run(name="Dawlance DW-131 AC")["product_name_no_abbreviation"].passed


def test_slug_length_can_fail():
    assert not _run(name="Y" * 200)["slug_length"].passed


def test_focus_keyword_is_coherent_primary_can_fail():
    assert not _run(keyword="something, comma stacked")["focus_keyword_is_coherent_primary"].passed


def test_seo_title_contains_focus_keyword_can_fail():
    assert not _run(title="Totally Unrelated Title | Buy Smart")["seo_title_contains_focus_keyword"].passed


def test_seo_title_power_word_can_fail():
    assert not _run(title=KEYWORD)["seo_title_power_word"].passed


def test_seo_title_contains_number_can_fail():
    assert not _run(title="Dawlance Inverter Air Conditioner | Buy Smart")["seo_title_contains_number"].passed


def test_focus_keyword_in_subheading_can_fail():
    assert not _run(content="body text with no product name at all")["focus_keyword_in_subheading"].passed


def test_meta_description_length_can_fail():
    assert not _run(writer=_writer(rank_math_description="too short"))["meta_description_length_150_160"].passed


def test_meta_description_begins_with_focus_keyword_can_fail():
    bad = "Some other opening sentence entirely that does not lead with the keyword at all here."
    assert not _run(writer=_writer(rank_math_description=bad))["meta_description_begins_with_focus_keyword"].passed


def test_meta_description_mentions_warranty_can_fail():
    """A dropped warranty duration must be caught."""
    no_warranty = f"{KEYWORD} delivers reliable cooling for your home every day. {CTA}"
    assert not _run(writer=_writer(rank_math_description=no_warranty))["meta_description_mentions_warranty"].passed


def test_meta_description_ends_with_cta_can_fail():
    assert not _run(writer=_writer(rank_math_description=f"{KEYWORD} with {WARRANTY} and no closing call."))[
        "meta_description_ends_with_cta"].passed


def test_lsi_keyword_count_is_enforced_before_the_check_even_runs():
    """
    Pydantic strictly requires 2-3 LSI keywords. If the LLM generates 1 or 4,
    the model fails validation and retry kicks in.
    """
    with pytest.raises(Exception):
        _writer(lsi_keywords=["only one"])


def test_lsi_keywords_present_in_body_can_fail():
    assert not _run(content="body copy that omits every lsi phrase")["lsi_keywords_present_in_body"].passed


def test_image_alt_text_valid_can_fail():
    assert not _run(writer=_writer(alt_text_1="totally unrelated alt text"))["image_alt_text_valid"].passed


def test_first_10_percent_rule_can_fail():
    late = ("filler sentence " * 200) + KEYWORD
    assert not _run(content=late)["first_10_percent_rule"].passed


def test_content_length_minimum_can_fail():
    assert not _run(content=f"{KEYWORD} short body.")["content_length_minimum"].passed


def test_keyword_density_can_fail_when_too_low():
    sparse = KEYWORD + (" filler word here " * 400)
    assert not _run(content=sparse)["keyword_density_in_range"].passed


def test_keyword_density_can_fail_when_stuffed():
    stuffed = (KEYWORD + " ") * 60
    assert not _run(content=stuffed)["keyword_density_in_range"].passed


# --- The guard that keeps this file honest ----------------------------------

def test_every_emitted_check_has_a_failure_test():
    """
    Enumerates the checks the validator actually emits and asserts each one is
    covered above. A newly added check cannot ship without proof it can fail --
    which is exactly how a permanently-passing check would otherwise slip in.
    """
    emitted = set(_run().keys())

    covered = {
        "product_name_length", "product_name_no_abbreviation", "slug_length",
        "focus_keyword_is_coherent_primary", "seo_title_contains_focus_keyword",
        "seo_title_power_word", "seo_title_contains_number",
        "focus_keyword_in_subheading", "meta_description_length_150_160",
        "meta_description_begins_with_focus_keyword",
        "meta_description_mentions_warranty", "meta_description_ends_with_cta",
        "lsi_keyword_count", "lsi_keywords_present_in_body",
        "image_alt_text_valid", "first_10_percent_rule",
        "content_length_minimum", "keyword_density_in_range",
    }

    uncovered = emitted - covered
    assert not uncovered, (
        f"These checks have no proof they can FAIL: {sorted(uncovered)}. "
        f"Add a failing-input test for each in this file."
    )

    stale = covered - emitted
    assert not stale, f"These checks no longer exist and should be removed here: {sorted(stale)}"


def test_a_fully_correct_product_passes_everything():
    """The mirror image: valid input must not trip any check."""
    failing = [name for name, check in _run().items() if not check.passed]
    assert not failing, f"A correct product should pass everything, but these failed: {failing}"
