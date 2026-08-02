"""
Template B (no-image) renders the store's WoodMart theme: accent-bordered <h2>
sections, a "Key Specifications & Benefits" box, and a FAQ accordion. Presentation
is theme-accurate, and the first heading carries the focus keyword so the live
Rank Math "keyword in subheading" test passes.
"""
from app.builders.description_merger import render_template_b
from app.models.writer_output import FAQPair, WriterOutput

FK = "WestPoint Pakistan WF-6807"
NAME = "WestPoint Pakistan WF-6807 Deluxe Hair Straightener"


def _wo(**overrides) -> WriterOutput:
    base = dict(
        hero_heading="Premium Styling at Home",
        hero_paragraph="A great tool for daily styling.",
        feature_headings=["Overview & Design", "Advanced Performance"],
        feature_texts=["Ceramic plates for smooth glide.", "Fast, even heat every time."],
        features_bullets=[
            "Ceramic Coating Plate: Glides smoothly and reduces frizz.",
            "Fast Heat-Up: Ready in seconds for quick styling.",
        ],
        faqs=[FAQPair(question=f"Q{i}?", answer=f"A{i}.") for i in range(4)]
        + [FAQPair(question="What is the official warranty?", answer="2 Years Warranty.")],
        short_desc_feature_1="a", short_desc_feature_2="b", short_desc_feature_3="c",
        rank_math_description="d" * 152,
        lsi_keywords=["ceramic straightener", "flat iron", "hair styling tool"],
        alt_text_1=FK, alt_text_2=FK, alt_text_3=FK,
    )
    base.update(overrides)
    return WriterOutput(**base)


def test_uses_theme_accent_colours_and_structure():
    html = render_template_b(_wo(), NAME, focus_keyword=FK)
    assert "#561491" in html and "#F7A800" in html          # brand + gold accents
    assert "border-left: 5px solid #F7A800" in html          # section h2 style
    assert "Key Specifications &amp; Benefits" in html        # spec box
    assert "<details" in html and "<summary" in html          # FAQ accordion
    assert "Frequently Asked Questions" in html


def test_first_heading_carries_the_focus_keyword():
    # hero_heading lacks the keyword -> the product name (which contains it) is used.
    html = render_template_b(_wo(hero_heading="Premium Styling"), NAME, focus_keyword=FK)
    first_h2 = html.split("</h2>")[0]
    assert FK.lower() in first_h2.lower()


def test_spec_bullet_term_is_bolded():
    html = render_template_b(_wo(), NAME, focus_keyword=FK)
    assert "<strong style='font-family: var(--wd-title-font);'>Ceramic Coating Plate:</strong>" in html


def test_stray_markdown_asterisks_are_stripped_from_bullets():
    wo = _wo(features_bullets=["**Ceramic Coating Plate**: Reduces frizz.", "Fast Heat: Ready fast."])
    html = render_template_b(wo, NAME, focus_keyword=FK)
    assert "**" not in html  # literal asterisks must never reach the rendered HTML
    assert "<strong style='font-family: var(--wd-title-font);'>Ceramic Coating Plate:</strong>" in html


def test_faq_answers_and_questions_are_present():
    html = render_template_b(_wo(), NAME, focus_keyword=FK)
    assert "Q1: Q0?" in html or "Q1:" in html   # numbered summaries
    assert "official warranty" in html.lower()
    assert "2 Years Warranty" in html
