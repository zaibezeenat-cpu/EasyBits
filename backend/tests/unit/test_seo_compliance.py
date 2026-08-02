"""
Deterministic SEO compliance for the Writer's output.

The Writer is an LLM and will not reliably self-limit how often it repeats the
(long) focus keyword -- the Haier/Westpoint pilots showed 9 exact repeats at ~3%
density despite the prompt asking for 3-5 and despite retry feedback. Rather than
fight the model, this caps density deterministically (the same philosophy as the
already-deterministic name and meta-description builders): keep the first few
occurrences, replace the surplus with a natural short form (the model number).
"""
from app.builders.seo_compliance import enforce_keyword_density, ensure_lsi_in_body
from app.models.writer_output import FAQPair, WriterOutput

FK = "WestPoint Pakistan WF-6807 Hair Straightener"
FILLER = "It heats fast and glides smoothly for salon results at home. " * 24  # ~240 words


def _wo(**overrides) -> WriterOutput:
    base = dict(
        hero_heading=f"{FK} Overview",
        hero_paragraph=f"The {FK} is premium. {FILLER} Buy the {FK} now. The {FK} shines.",
        feature_headings=["Ceramic Plates", "Fast Heat"],
        feature_texts=[f"{FK} plate detail.", f"{FK} heat detail."],
        features_bullets=[f"{FK} bullet one", "Plain bullet two"],
        faqs=[FAQPair(question=f"Q{i}?", answer=f"{FK} answer {i}.") for i in range(4)]
        + [FAQPair(question="What is the official warranty?", answer="2 Years Warranty.")],
        short_desc_feature_1="a", short_desc_feature_2="b", short_desc_feature_3="c",
        rank_math_description="d" * 152,
        lsi_keywords=["ceramic straightener", "hair styling tool", "flat iron"],
        alt_text_1=FK, alt_text_2=FK, alt_text_3=FK,
    )
    base.update(overrides)
    return WriterOutput(**base)


def _segments(wo: WriterOutput) -> list[str]:
    return [wo.hero_heading, wo.hero_paragraph, *wo.feature_texts, *wo.features_bullets,
            *[f.answer for f in wo.faqs]]


def _occ_density(wo: WriterOutput) -> tuple[int, float]:
    text = " ".join(_segments(wo))
    occ = text.lower().count(FK.lower())
    wc = len(text.split())
    return occ, (occ / wc if wc else 0.0)


def test_overused_keyword_is_capped_below_ceiling():
    before_occ, before_density = _occ_density(_wo())
    assert before_density > 0.025, "fixture must start over the ceiling to be a real test"

    out = enforce_keyword_density(_wo(), FK, replacement="WF-6807", max_density=0.025)
    occ, density = _occ_density(out)
    assert density <= 0.025, f"density still {density:.3f}"
    assert occ >= 3, "must keep at least the Rank Math minimum of 3"


def test_first_occurrence_is_kept_for_seo_position():
    out = enforce_keyword_density(_wo(), FK, replacement="WF-6807")
    # The hero heading is the highest-value slot; its keyword must survive.
    assert FK.lower() in out.hero_heading.lower()


def test_surplus_is_replaced_with_the_given_short_form():
    out = enforce_keyword_density(_wo(), FK, replacement="WF-6807")
    assert "WF-6807" in " ".join(_segments(out))


def test_missing_lsi_keyword_is_woven_into_the_body():
    wo = _wo(lsi_keywords=["ceramic straightener", "hair styling tool", "brand-new-term xyz"])
    # "brand-new-term xyz" is not anywhere in the fixture body.
    out = ensure_lsi_in_body(wo, wo.lsi_keywords)
    body = " ".join([out.hero_paragraph, *out.feature_texts, *out.features_bullets,
                     *[f.answer for f in out.faqs]]).lower()
    for kw in wo.lsi_keywords:
        assert kw.lower() in body, f"{kw} still missing"


def test_present_lsi_keywords_leave_body_unchanged():
    wo = _wo()
    # All fixture LSI keywords are absent from the body, so this also proves the
    # guard only touches what is missing -- craft one that IS present.
    wo.hero_paragraph += " It is a proper ceramic straightener and flat iron and hair styling tool."
    before = wo.hero_paragraph
    out = ensure_lsi_in_body(wo, wo.lsi_keywords)
    assert out.hero_paragraph == before  # nothing to add


def test_already_compliant_content_is_unchanged():
    lean = _wo(
        hero_heading=f"{FK} Overview",
        hero_paragraph=f"A great tool. {FILLER}",
        feature_texts=["Ceramic plates detail.", "Fast heat detail."],
        features_bullets=["Bullet one", "Bullet two"],
        faqs=[FAQPair(question=f"Q{i}?", answer="Plain answer.") for i in range(4)]
        + [FAQPair(question="What is the official warranty?", answer="2 Years Warranty.")],
    )
    occ_before, density_before = _occ_density(lean)
    assert density_before <= 0.025
    out = enforce_keyword_density(lean, FK, replacement="WF-6807")
    assert _occ_density(out)[0] == occ_before  # nothing replaced
