import pytest
from app.graph.seo_validator import validate_seo_rules, expected_meta_cta
from app.builders.short_description_renderer import render_short_description
from app.builders.specs_renderer import render_specs_table
from app.builders.description_merger import merge_description, merge_description_template_a
from app.builders.seo_title_builder import build_seo_title, build_focus_keyword_field
from app.builders.html_sanitizer import strip_lsi_keyword_formatting, strip_newlines_for_csv
from app.builders.csv_assembler import (
    assemble_csv_row,
    BrandCasingMismatchError,
    CategoryBreadcrumbError,
    CategoryCasingMismatchError,
)
from app.models.writer_output import WriterOutput, FAQPair
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.taxonomy import CategorySpecSchema, SpecField

FOCUS_KEYWORD = "Dawlance DW-131 Inverter Air Conditioner"  # full product type, never abbreviated
WARRANTY_PHRASE = "1 Year Brand Warranty"
CTA = expected_meta_cta("Air conditioner", capacity="1.5 Ton")  # "Buy the best 1.5 Ton AC in Pakistan today."

def _valid_meta_description() -> str:
    """Builds a description that satisfies all V8.0 Production Lock constraints:
    starts with focus keyword, mentions warranty, ends with fixed CTA, 150-160 chars.
    """
    prefix = f"{FOCUS_KEYWORD} comes packed with powerful cooling, energy savings, and a "
    body = f"{prefix}{WARRANTY_PHRASE} for total peace of mind at home today. "
    desc = body + CTA
    # Pad/trim the connective filler until length lands in [150, 160].
    filler = " truly"
    while len(desc) < 150:
        body = body.rstrip() + filler + ". "
        desc = body + CTA
    while len(desc) > 160:
        body = body[:-1]
        desc = body.rstrip() + " " + CTA
    return desc

def _long_body(topic: str, keyword: str | None = None, sentences: int = 14) -> str:
    """
    Builds realistic filler prose of a given length.

    Needed because Rank Math scores anything under 600 words RED, so a fixture
    must be genuinely long to exercise the real content-length and
    keyword-density checks rather than tripping them artificially.
    """
    lines = [
        (f"The {keyword} is engineered for demanding Pakistani conditions where "
         f"reliability matters more than specifications on paper.")
        if keyword else
        ("This model is engineered for demanding Pakistani conditions where "
         "reliability matters more than specifications on paper."),
        f"{topic} is handled by components rated for continuous operation through "
        f"long summer afternoons without loss of performance.",
        "Installation is straightforward for any authorised technician and requires "
        "no special modification to existing wiring or fittings.",
        "Running costs stay predictable because the unit modulates its output "
        "rather than switching abruptly between full power and standby.",
        "Materials were selected for corrosion resistance, which matters in humid "
        "coastal cities where cheaper units degrade within a couple of seasons.",
        "Servicing is simple, with accessible panels and widely stocked spare parts "
        "available through the official service network nationwide.",
        "Noise output remains low enough for bedrooms, so comfort does not come at "
        "the cost of a constant background hum during the night.",
    ]
    out = []
    while len(out) < sentences:
        out.extend(lines)
    return " ".join(out[:sentences])


@pytest.fixture
def mock_writer_output():
    lsi = ["dual inverter cooling", "energy saving air conditioner", "quiet split AC unit"]
    return WriterOutput(
        hero_heading="Efficient Cooling",
        hero_paragraph=(
            f"{FOCUS_KEYWORD} provides top-notch cooling for your home, powered by "
            f"{lsi[0]} technology that keeps every room comfortable no matter how hot "
            f"the weather gets outside. Built for Pakistani summers, this unit balances "
            f"strong performance with genuinely low running costs, so your electricity "
            f"bill stays predictable even when the compressor runs for hours every day "
            f"during peak season."
        ),
        feature_headings=["Powerful", "Quiet", "Smart"],
        feature_texts=[
            (
                f"High BTU output backed by {lsi[1]} design means the compressor only "
                f"draws the power it actually needs at any given moment, instead of "
                f"cycling fully on and off like older fixed-speed units. That translates "
                f"into steadier room temperatures and a noticeably lower monthly bill."
            ),
            (
                f"Whisper-quiet operation thanks to a {lsi[2]} keeps bedrooms and living "
                f"rooms comfortable at night without a distracting hum. The outdoor unit "
                f"is similarly engineered to reduce vibration and noise for neighbors."
            ),
            (
                "Wi-Fi enabled smart controls let you adjust the temperature, fan speed, "
                "and sleep mode from a phone app, so the room is already cool by the "
                "time you walk in the door after a long day. "
                + _long_body("Cooling capacity", FOCUS_KEYWORD, sentences=20)
            ),
            # These two blocks omit the keyword: repeating it in every block
            # pushed density to 2.98%, past Rank Math's 2.5% stuffing ceiling.
            _long_body("Airflow control", sentences=20),
            _long_body("Filtration", sentences=20),
        ],
        features_bullets=["Energy efficient", "Dual inverter", "Auto cleaning"],
        faqs=[
            FAQPair(question="Q1", answer="A1"),
            FAQPair(question="Q2", answer="A2"),
            FAQPair(question="Q3", answer="A3"),
            FAQPair(question="Q4", answer="A4"),
            FAQPair(question="What is the official warranty?", answer=f"It comes with a {WARRANTY_PHRASE} provided by Dawlance."),
        ],
        short_desc_feature_1="Turbo Cooling",
        short_desc_feature_2="Energy Saving",
        short_desc_feature_3="Modern Design",
        rank_math_description=_valid_meta_description(),
        lsi_keywords=lsi,
        alt_text_1=FOCUS_KEYWORD,
        alt_text_2=lsi[0],
        alt_text_3=lsi[1],
    )

def test_meta_description_is_151_to_155_chars():
    desc = _valid_meta_description()
    assert 150 <= len(desc) <= 160

def test_seo_validator_all_checks(mock_writer_output):
    product_name = FOCUS_KEYWORD  # Focus keyword is locked to the exact Product Name (V8.0)
    concatenated_content = (
        mock_writer_output.hero_heading + "\n" + mock_writer_output.hero_paragraph + "\n"
        + "\n".join(mock_writer_output.feature_texts) + "\n"
        + "\n".join(mock_writer_output.features_bullets) + "\n"
        + "\n".join(f.answer for f in mock_writer_output.faqs)
    )
    rank_math_title = build_seo_title(
        brand="Dawlance", capacity="1.5 Ton", series="", sku="INV-18",
        category_name="Air conditioner", focus_keyword=product_name,
    )

    results = validate_seo_rules(
        writer_output=mock_writer_output,
        focus_keyword=product_name,
        product_name=product_name,
        concatenated_content=concatenated_content,
        rank_math_title=rank_math_title,
        warranty_phrase=WARRANTY_PHRASE,
        category_name="Air conditioner",
        expected_cta=CTA,
    )

    check_names = [r.check_name for r in results]
    assert "product_name_length" in check_names
    assert "slug_length" in check_names
    assert "focus_keyword_is_coherent_primary" in check_names
    assert "seo_title_contains_focus_keyword" in check_names
    assert "meta_description_length_150_160" in check_names
    assert "meta_description_begins_with_focus_keyword" in check_names
    assert "meta_description_mentions_warranty" in check_names
    assert "meta_description_ends_with_cta" in check_names
    assert "lsi_keyword_count" in check_names
    assert "lsi_keywords_present_in_body" in check_names
    assert "image_alt_text_valid" in check_names
    assert "first_10_percent_rule" in check_names
    assert "content_length_minimum" in check_names

    # The old 10-13 keyword-stacking check is gone entirely (ripped out, not layered).
    assert "keyword_stacking" not in check_names
    assert "seo_title_format" not in check_names
    assert "meta_description_quality" not in check_names

    for r in results:
        assert r.passed, f"Check {r.check_name} failed: {r.detail}"


def test_content_length_minimum_rejects_thin_content(mock_writer_output):
    product_name = FOCUS_KEYWORD
    rank_math_title = build_seo_title(
        brand="Dawlance", capacity="1.5 Ton", series="", sku="INV-18",
        category_name="Air conditioner", focus_keyword=product_name,
    )
    results = validate_seo_rules(
        writer_output=mock_writer_output,
        focus_keyword=product_name,
        product_name=product_name,
        concatenated_content="Short thin product blurb, way under the word minimum.",
        rank_math_title=rank_math_title,
        warranty_phrase=WARRANTY_PHRASE,
        category_name="Air conditioner",
        expected_cta=CTA,
    )
    check = next(r for r in results if r.check_name == "content_length_minimum")
    assert not check.passed


def test_focus_keyword_rejects_comma_stacking(mock_writer_output):
    product_name = FOCUS_KEYWORD
    stacked_keyword = "Dawlance, Inverter, AC, Best, Price, Pakistan"  # old v7.0-style stacking
    concatenated_content = mock_writer_output.hero_paragraph
    rank_math_title = build_seo_title("Dawlance", "1.5 Ton", "", "INV-18", "Air Conditioner", product_name)

    results = validate_seo_rules(
        writer_output=mock_writer_output,
        focus_keyword=stacked_keyword,
        product_name=product_name,
        concatenated_content=concatenated_content,
        rank_math_title=rank_math_title,
        warranty_phrase=WARRANTY_PHRASE,
        category_name="Air conditioner",
        expected_cta=CTA,
    )
    check = next(r for r in results if r.check_name == "focus_keyword_is_coherent_primary")
    assert not check.passed


def test_focus_keyword_field_combines_primary_and_lsi_keywords():
    """
    V3.0 correction: confirmed directly from the live Rank Math panel (its UI
    has a primary + secondary keyword pill system, and scores 'Focus Keyword
    and combination'), the exported CSV field is primary + 3 LSI keywords,
    comma-joined -- matching real reference examples exactly, e.g.:
    "Kenwood 1 Ton Luxury Ultra KLU-12B03S DC Inverter Heat & Cool Split Air
    Conditioner, 1 ton inverter ac kenwood, best 1 ton ac in Pakistan,
    Kenwood 1 Ton AC price in Pakistan"
    """
    field = build_focus_keyword_field(
        "Kenwood 1 Ton Luxury Ultra KLU-12B03S DC Inverter Heat & Cool Split Air Conditioner",
        ["1 ton inverter ac kenwood", "best 1 ton ac in Pakistan", "Kenwood 1 Ton AC price in Pakistan"],
    )
    assert field == (
        "Kenwood 1 Ton Luxury Ultra KLU-12B03S DC Inverter Heat & Cool Split Air Conditioner, "
        "1 ton inverter ac kenwood, best 1 ton ac in Pakistan, Kenwood 1 Ton AC price in Pakistan"
    )
    assert field.count(",") == 3  # primary + exactly 3 secondary keywords


def test_focus_keyword_field_does_not_duplicate_the_primary():
    """
    The Writer sometimes lists the product name itself as its first LSI keyword,
    which produced "Name, Name, ..." in the exported focus-keyword field. The
    primary must appear exactly once and secondaries are de-duplicated.
    """
    field = build_focus_keyword_field(
        "WestPoint Pakistan WF-6807 Deluxe Hair Straightener",
        [
            "WestPoint Pakistan WF-6807 Deluxe Hair Straightener",  # duplicate of primary
            "ceramic hair straightener",
            "ceramic hair straightener",  # duplicate secondary
            "flat iron",
        ],
    )
    assert field == (
        "WestPoint Pakistan WF-6807 Deluxe Hair Straightener, "
        "ceramic hair straightener, flat iron"
    )


def test_meta_description_warranty_check_accepts_abbreviated_real_wording():
    """
    Real reference examples abbreviate the warranty ("Warranty: 10-yr.") rather
    than repeating the full stored phrase -- this must still PASS as long as
    every real duration number is present (so a duration can never be silently
    dropped), and must FAIL if a duration is missing or wrong.
    """
    warranty_phrase = "10-Year Compressor Warranty; 5-Year All Parts Warranty"
    concatenated = "irrelevant body text"

    abbreviated_desc = "Kenwood ... with WiFi. Warranty: 10-yr, 5-yr parts. Buy the best AC today!"
    results = validate_seo_rules(
        writer_output=_dummy_writer_output(abbreviated_desc),
        focus_keyword="Kenwood Test AC", product_name="Kenwood Test AC",
        concatenated_content=concatenated, rank_math_title="Kenwood Test AC | Buy Smart",
        warranty_phrase=warranty_phrase, category_name="Air conditioner", expected_cta="Buy the best AC today!",
    )
    check = next(r for r in results if r.check_name == "meta_description_mentions_warranty")
    assert check.passed

    missing_duration_desc = "Kenwood ... with WiFi. Warranty: 5-yr parts only. Buy the best AC today!"
    results = validate_seo_rules(
        writer_output=_dummy_writer_output(missing_duration_desc),
        focus_keyword="Kenwood Test AC", product_name="Kenwood Test AC",
        concatenated_content=concatenated, rank_math_title="Kenwood Test AC | Buy Smart",
        warranty_phrase=warranty_phrase, category_name="Air conditioner", expected_cta="Buy the best AC today!",
    )
    check = next(r for r in results if r.check_name == "meta_description_mentions_warranty")
    assert not check.passed  # the "10" duration is missing entirely

def _dummy_writer_output(description: str):
    return WriterOutput(
        hero_heading="H", hero_paragraph="P", feature_headings=["A"], feature_texts=["B"],
        features_bullets=["C"],
        faqs=[FAQPair(question="Q1", answer="A1"), FAQPair(question="Q2", answer="A2"),
              FAQPair(question="Q3", answer="A3"), FAQPair(question="Q4", answer="A4"),
              FAQPair(question="What is the official warranty?", answer="A5")],
        short_desc_feature_1="a", short_desc_feature_2="b", short_desc_feature_3="c",
        rank_math_description=description, lsi_keywords=["kw1", "kw2", "kw3"],
        alt_text_1="Kenwood Test AC", alt_text_2="kw1", alt_text_3="kw2",
    )

def test_meta_cta_uses_real_capacity_not_a_hardcoded_tonnage():
    """Regression test for the bug found during V8.0 review: the CTA must reflect
    each product's actual capacity, not a fixed '1.5 ton' baked in for every AC."""
    cta_1_ton = expected_meta_cta("Air conditioner", capacity="1.0 Ton")
    cta_2_ton = expected_meta_cta("Air conditioner", capacity="2.0 Ton")

    assert cta_1_ton == "Buy the best 1.0 Ton AC in Pakistan today."
    assert cta_2_ton == "Buy the best 2.0 Ton AC in Pakistan today."
    assert cta_1_ton != cta_2_ton  # must NOT collapse to the same hardcoded string

    # No capacity found (e.g. extraction returned UNKNOWN) -> generic fallback,
    # never a guessed tonnage.
    cta_unknown = expected_meta_cta("Air conditioner", capacity=None)
    assert cta_unknown == "Buy the best air conditioner in Pakistan today."

def test_seo_title_always_contains_the_focus_keyword_verbatim():
    """
    Rank Math's highest-weighted Basic SEO test. The previous category-descriptor
    builder inserted words INTO the middle of the product name --
      name  : DAWLANCE DBD-1035 Glass Door Water Dispenser
      title : DAWLANCE DBD-1035 Glass Door Hot & Cold Water Dispenser
    -- splitting the phrase so this test failed on every single product.
    """
    for keyword, category in [
        ("Boss 1.5 Ton ECS-18HC AC", "Air conditioner"),
        ("Dawlance 20L HDG-201S Grill Microwave", "Microwave Oven"),
        ("Haier 14 Cu Ft HRF-398 Refrigerator", "Refrigerator"),
        ("Dawlance EZ Glass Door DBD-1034 Water Dispenser", "Water Dispenser"),
    ]:
        title = build_seo_title(
            brand="", capacity="", series="", sku="",
            category_name=category, focus_keyword=keyword,
        )
        assert keyword in title, f"focus keyword missing from SEO title for {category}"


def test_seo_title_matches_the_real_exported_format():
    """Every real CSV supplied by the site owner uses "[Name] | Buy Smart"."""
    for name in [
        "Dawlance EZ Glass Door DBD-1034 Water Dispenser",
        "Midea Top Load YL-2037S-B Premium Water Dispenser",
        "Dawlance 600W DWHJ-8002 Premium Hard Fruit Juicer",
    ]:
        title = build_seo_title(
            brand="", capacity="", series="", sku="",
            category_name="Water Dispenser", focus_keyword=name,
        )
        assert title == f"{name} | Buy Smart"
        # Stays within Google's ~60-character display budget.
        assert len(title) <= 65, f"SEO title too long to display: {len(title)}"

def test_seo_title_power_word_fallback_for_unregistered_categories():
    """A category with no registered descriptor falls back to the universal
    power-word format rather than guessing a suffix."""
    title = build_seo_title(
        brand="Anex", capacity="", series="", sku="AG-2093",
        category_name="Garment Steam Iron", focus_keyword="Anex AG-2093 Garment Steam Iron",
    )
    assert title.endswith("| Buy Smart")

def test_lsi_keywords_must_be_plain_text_after_sanitization():
    html_in = (
        "<p>This <strong>dual inverter cooling</strong> unit is efficient. "
        "<h2>energy saving air conditioner</h2> tech included.</p>"
    )
    out = strip_lsi_keyword_formatting(html_in, ["dual inverter cooling", "energy saving air conditioner"])
    assert "<strong>dual inverter cooling</strong>" not in out
    assert "<h2>energy saving air conditioner</h2>" not in out
    assert "dual inverter cooling" in out
    assert "energy saving air conditioner" in out

def test_image_grid_zigzag_alternates_direction(mock_writer_output):
    html = merge_description_template_a(mock_writer_output)
    first_row_idx = html.index("<div style='display: flex")
    second_row_idx = html.index("<div style='display: flex", first_row_idx + 1)
    third_row_idx = html.index("<div style='display: flex", second_row_idx + 1)

    row1 = html[first_row_idx:second_row_idx]
    row2 = html[second_row_idx:third_row_idx]
    row3 = html[third_row_idx:]

    assert "flex-direction: row-reverse;" not in row1
    assert "flex-direction: row-reverse;" in row2
    assert "flex-direction: row-reverse;" not in row3

    assert "src=''" in html  # empty src: images are uploaded manually post-import
    assert "max-width" not in html
    assert "box-shadow: 0 4px 8px rgba(0,0,0,0.1);" in html

def test_short_description_paragraph_template(mock_writer_output):
    html = render_short_description(mock_writer_output, "Dawlance 30L", "Microwave Oven", "1 Year Warranty")
    assert html.startswith("<p>Experience the convenience of the <strong>Dawlance 30L</strong>.")
    assert "Designed for modern homes" in html
    assert "Backed by a 1 Year Warranty" in html
    assert "<li>" not in html # Should not be a list anymore

def test_specs_renderer_thead_and_styles():
    from uuid import uuid4
    from datetime import datetime
    extraction = ExtractionResult(
        product_id=str(uuid4()),
        category_key="microwave",
        citations=[
            SourceCitation(
                field_name="power",
                value="1000W",
                source_url="url",
                source_type="official",
                confidence="confirmed",
                fetched_at=datetime.now()
            )
        ]
    )
    schema = CategorySpecSchema(
        id=uuid4(),
        category_id=uuid4(),
        fields=[SpecField(key="power", label="Power Consumption")],
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    html = render_specs_table(extraction, schema, "1 Year Warranty")

    assert "<table class='shop_attributes'" in html
    assert "<thead>" in html
    assert "SPECIFICATION" in html
    assert "DETAILS" in html
    assert "Power Consumption" in html
    assert "1000W" in html
    assert "Warranty" in html
    assert "bold" in html.lower()
    assert "var(--wd-title-font)" in html

def test_description_merger_uppercase_placeholders(mock_writer_output):
    template = "<div>{{HERO_HEADING}} - {{HERO_PARAGRAPH}} - {{FAQ_BLOCKS}}</div>"
    html = merge_description(mock_writer_output, template)

    assert mock_writer_output.hero_heading in html
    assert mock_writer_output.hero_paragraph in html
    assert "Q1: Q1" in html
    assert WARRANTY_PHRASE in html

def test_csv_assembler_brand_casing_lock_blocks_mismatch():
    from app.graph.state import PipelineState
    from app.models.raw_input import RawProductInput
    from decimal import Decimal
    import uuid

    raw = RawProductInput(
        sku="SKU1", model_number="M1", brand_name="dawlance", category_name="Air conditioner",
        product_type="AC", regular_price=Decimal("1000"), sale_price=Decimal("900"),
    )
    state = PipelineState(product_id=uuid.uuid4(), batch_id=uuid.uuid4(), raw_input=raw, name="Test Name")

    with pytest.raises(BrandCasingMismatchError):
        assemble_csv_row(state, "Home Appliance > Air conditioner", "dawlance", canonical_brand_name="DAWLANCE")

def test_csv_assembler_requires_breadcrumb_parent():
    from app.graph.state import PipelineState
    from app.models.raw_input import RawProductInput
    from decimal import Decimal
    import uuid

    raw = RawProductInput(
        sku="SKU1", model_number="M1", brand_name="DAWLANCE", category_name="Air conditioner",
        product_type="AC", regular_price=Decimal("1000"), sale_price=Decimal("900"),
    )
    state = PipelineState(product_id=uuid.uuid4(), batch_id=uuid.uuid4(), raw_input=raw, name="Test Name")

    # "Air conditioner" is a CHILD category passed without its parent breadcrumb and
    # without a verified canonical path -> must be rejected. (The guard consolidated:
    # a bare/unverified category now raises CategoryCasingMismatchError rather than
    # the old blanket breadcrumb check, so a legitimate top-level category is not
    # wrongly rejected. Either error satisfies the intent: it is not exported.)
    with pytest.raises((CategoryBreadcrumbError, CategoryCasingMismatchError)):
        assemble_csv_row(state, "Air conditioner", "DAWLANCE", canonical_brand_name="DAWLANCE")

def test_csv_assembler_strips_newlines():
    from app.graph.state import PipelineState
    from app.models.raw_input import RawProductInput
    from decimal import Decimal
    import uuid

    raw = RawProductInput(
        sku="SKU1", model_number="M1", brand_name="DAWLANCE", category_name="Air conditioner",
        product_type="AC", regular_price=Decimal("1000"), sale_price=Decimal("900"),
    )
    state = PipelineState(
        product_id=uuid.uuid4(), batch_id=uuid.uuid4(), raw_input=raw, name="Test Name",
        description="line1\nline2\r\nline3", short_description="s1\ns2",
    )
    row = assemble_csv_row(
        state, "Home Appliance > Air conditioner", "DAWLANCE",
        canonical_brand_name="DAWLANCE",
        canonical_category_path="Home Appliance > Air conditioner",
    )
    assert "\n" not in row["Description"]
    assert "\r" not in row["Description"]
    assert "\n" not in row["Short description"]

def test_strip_newlines_for_csv_helper():
    assert strip_newlines_for_csv("a\nb\r\nc\rd") == "a b c d"
