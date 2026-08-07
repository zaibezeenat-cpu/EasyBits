"""
Tests for the heavy pipeline nodes: writer, reviewer, deterministic builders and
CSV assembly, with the LLM and database mocked.

These are the nodes that actually produce what gets published, so the assertions
focus on the guarantees that protect the live store: deterministic fields are
never taken from the LLM, the warranty is identical everywhere it appears, and
the CSV keeps its exact 51-column shape.
"""
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.graph import nodes
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.raw_input import RawProductInput
from app.models.review_result import ReviewResult
from app.models.taxonomy import CategorySpecSchema, SpecField
from app.models.writer_output import FAQPair, WriterOutput

WARRANTY = "1 Year Official Warranty"


def _schema() -> CategorySpecSchema:
    now = datetime.now(UTC)
    return CategorySpecSchema(
        id=uuid4(), category_id=uuid4(), created_at=now, updated_at=now,
        fields=[
            SpecField(key="capacity", label="Capacity", required=True),
            SpecField(key="features", label="Features", required=False),
        ],
    )


def _extraction() -> ExtractionResult:
    now = datetime.now(UTC)
    return ExtractionResult(
        product_id=str(uuid4()), category_key="air_conditioner",
        citations=[
            SourceCitation(field_name="capacity", value="1 Ton", source_url="https://s.pk/p",
                           source_type="official", confidence="confirmed", fetched_at=now),
            SourceCitation(field_name="features", value="WiFi", source_url="https://s.pk/p",
                           source_type="official", confidence="confirmed", fetched_at=now),
        ],
        image_urls=[],
    )


def _writer_output() -> WriterOutput:
    lsi = ["inverter ac", "energy saving ac", "split air conditioner"]
    body = (
        "Kenwood KLU-12B03S is an inverter ac built for Pakistani summers, an "
        "energy saving ac that keeps rooms cool. This split air conditioner "
        "delivers steady comfort with low running costs across long hot days."
    )
    return WriterOutput(
        hero_heading="Cool Comfort",
        hero_paragraph=body,
        feature_headings=["Powerful", "Quiet", "Smart"],
        feature_texts=[body, body, body],
        features_bullets=["Efficient", "Quiet", "Smart", "Durable"],
        faqs=[
            FAQPair(question="Q1", answer="A1"),
            FAQPair(question="Q2", answer="A2"),
            FAQPair(question="Q3", answer="A3"),
            FAQPair(question="Q4", answer="A4"),
            FAQPair(question="What is the official warranty?",
                    answer=f"It comes with a {WARRANTY} provided by Kenwood."),
        ],
        short_desc_feature_1="Fast cooling",
        short_desc_feature_2="Low power",
        short_desc_feature_3="Smart control",
        rank_math_description="x" * 152,
        lsi_keywords=lsi,
        alt_text_1=lsi[0], alt_text_2=lsi[1], alt_text_3=lsi[2],
    )


def _state(**overrides) -> PipelineState:
    base = {
        "product_id": uuid4(), "batch_id": uuid4(),
        "raw_input": RawProductInput(
            sku="KLU-12B03S", model_number="KLU-12B03S", brand_name="Kenwood",
            category_name="Air conditioner", product_type="Air conditioner",
            regular_price=Decimal(150000), sale_price=Decimal(139999),
            warranty_override=WARRANTY,
        ),
        "category_schema": _schema(),
        "extraction": _extraction(),
        "selected_template_type": "B",
    }
    base.update(overrides)
    return PipelineState(**base)


@pytest.fixture
def taxonomy(monkeypatch):
    class _Brand:
        id, name = uuid4(), "Kenwood"
        display_name = None
        title_name = "Kenwood"  # matches Brand.title_name (display_name or name)

    class _Cat:
        id, name, parent_id = uuid4(), "Air conditioner", uuid4()

    class _Parent:
        id, name, parent_id = uuid4(), "Home Appliance", None

    async def brand(_n):
        return _Brand()

    async def cat(_n):
        return _Cat()

    async def get(_id):
        return _Parent()

    async def phrase(*_a):
        return None  # forces warranty_override to be used

    async def official_sites(_brand):
        return ["https://kenwoodpakistan.pk"]

    monkeypatch.setattr(nodes.brands_repo, "get_by_name", brand)
    monkeypatch.setattr(nodes.categories_repo, "get_by_name", cat)
    monkeypatch.setattr(nodes.categories_repo, "get", get)
    monkeypatch.setattr(nodes.warranty_repo, "get_phrase", phrase)
    monkeypatch.setattr(nodes.sources_repo, "get_brand_aliases", official_sites)


# --- writer_node ------------------------------------------------------------

@pytest.mark.asyncio
async def test_writer_node_builds_deterministic_fields_not_llm_ones(taxonomy, monkeypatch):
    """
    Name, focus keyword and SEO title must come from the deterministic builders.
    Letting the LLM supply them is what caused inconsistent titles by hand.
    """
    async def fake_call(**_kwargs):
        return _writer_output()

    monkeypatch.setattr(nodes.llm_provider, "call", fake_call)

    result = await nodes.writer_node(_state())

    # Focus keyword is now the SHORT brand+model (primary), a substring of the full
    # Product Name -- not equal to it (which would be too long for natural density).
    assert result["rank_math_focus_keyword"] == "Kenwood KLU-12B03S"
    assert result["rank_math_focus_keyword"] in result["name"], "primary keyword must be in the name"
    assert result["rank_math_secondary_keyword"].startswith("KLU-12B03S"), "2nd keyword is model+type"
    assert result["rank_math_title"], "title must be built, not omitted"
    assert result["resolved_warranty_phrase"] == WARRANTY
    assert result["retry_count"] == 1


@pytest.mark.asyncio
async def test_writer_node_uses_sheet_warranty_over_matrix(taxonomy, monkeypatch):
    """The operator's per-product warranty is authoritative over the matrix."""
    async def fake_call(**_kwargs):
        return _writer_output()

    monkeypatch.setattr(nodes.llm_provider, "call", fake_call)
    result = await nodes.writer_node(_state())
    assert result["resolved_warranty_phrase"] == WARRANTY


@pytest.mark.asyncio
async def test_writer_node_escalates_without_any_warranty(taxonomy, monkeypatch):
    """
    No warranty from either source must NOT fall back to a placeholder: an
    unverified warranty is a claim the business would have to honour.
    """
    async def fake_call(**_kwargs):
        return _writer_output()

    monkeypatch.setattr(nodes.llm_provider, "call", fake_call)

    state = _state()
    state.raw_input.warranty_override = None
    result = await nodes.writer_node(state)
    assert result["manual_review_required"] is True


@pytest.mark.asyncio
async def test_writer_llm_failure_escalates_instead_of_crashing(taxonomy, monkeypatch):
    async def boom(**_kwargs):
        raise RuntimeError("all providers failed")

    monkeypatch.setattr(nodes.llm_provider, "call", boom)
    result = await nodes.writer_node(_state())
    assert result["manual_review_required"] is True
    assert result["failure"].category == "other"


# --- reviewer_node ----------------------------------------------------------

@pytest.mark.asyncio
async def test_reviewer_runs_deterministic_seo_checks(monkeypatch):
    async def fake_call(**_kwargs):
        return ReviewResult(passed=True, preflight_score=95, checks=[],
                            warranty_consistent=True, fact_cross_check_passed=True,
                            fact_cross_check_notes=[])

    monkeypatch.setattr(nodes.llm_provider, "call", fake_call)

    state = _state(writer_output=_writer_output(), name="Kenwood 1 Ton KLU-12B03S Air Conditioner",
                   rank_math_focus_keyword="Kenwood 1 Ton KLU-12B03S Air Conditioner",
                   rank_math_title="Kenwood 1 Ton KLU-12B03S Air Conditioner | Buy Smart",
                   resolved_warranty_phrase=WARRANTY,
                   meta_description_cta="Buy the best AC in Pakistan today.")

    result = await nodes.reviewer_node(state)
    review = result["review_result"]
    # Every deterministic check runs regardless of what the LLM said. The count
    # grew from 13 to 17 when the Rank Math gaps were closed (SEO title contains
    # the focus keyword, power word, number in title, keyword in subheading).
    assert len(review.checks) == 18
    names = {c.check_name for c in review.checks}
    for required in (
        "seo_title_contains_focus_keyword",
        "seo_title_power_word",
        "seo_title_contains_number",
        "focus_keyword_in_subheading",
        "keyword_density_in_range",
        "content_length_minimum",
    ):
        assert required in names, f"{required} must always run"


@pytest.mark.asyncio
async def test_reviewer_failure_escalates(monkeypatch):
    async def boom(**_kwargs):
        raise RuntimeError("reviewer unavailable")

    monkeypatch.setattr(nodes.llm_provider, "call", boom)

    state = _state(writer_output=_writer_output(), name="X", resolved_warranty_phrase=WARRANTY)
    result = await nodes.reviewer_node(state)
    assert result["manual_review_required"] is True


# --- deterministic builders + CSV -------------------------------------------

@pytest.mark.asyncio
async def test_builders_produce_all_content_fields(taxonomy):
    # Template B is now rendered deterministically (no DB skeleton), so no
    # templates_repo mock is needed.
    state = _state(writer_output=_writer_output(), name="Kenwood 1 Ton KLU-12B03S Air Conditioner",
                   rank_math_focus_keyword="Kenwood KLU-12B03S",
                   resolved_warranty_phrase=WARRANTY, selected_template_type="B")

    result = await nodes.deterministic_builders_node(state)
    assert result["short_description"] and result["description"]
    assert result["specs_table_html"]
    assert result["tags"] == "Kenwood, Air conditioner, HW"
    # The warranty must survive into the rendered output unchanged.
    assert WARRANTY in result["specs_table_html"]
    # Template B renders in the store theme: accent-bordered sections + FAQ accordion.
    assert "border-left: 5px solid #F7A800" in result["description"]
    assert "<details" in result["description"]


@pytest.mark.asyncio
async def test_csv_row_has_exactly_51_columns_and_parent_breadcrumb(taxonomy):
    from app.builders.csv_assembler import COLUMN_ORDER

    state = _state(writer_output=_writer_output(), name="Kenwood 1 Ton KLU-12B03S Air Conditioner",
                   rank_math_focus_keyword="Kenwood 1 Ton KLU-12B03S Air Conditioner",
                   rank_math_title="Kenwood 1 Ton KLU-12B03S Air Conditioner | Buy Smart",
                   resolved_warranty_phrase=WARRANTY,
                   short_description="<p>x</p>", description="<div>x</div>",
                   specs_table_html="<table></table>", tags="Kenwood, Air conditioner, HW")

    result = await nodes.csv_row_assembler_node(state)
    row = result["csv_row"]

    assert len(row) == 51
    assert list(row.keys()) == COLUMN_ORDER, "column ORDER must match exactly"
    assert row["Categories"] == "Home Appliance > Air conditioner"
    assert row["Brands"] == "Kenwood"
    # Sale must stay below regular in the exported row.
    assert float(row["Sale price"]) < float(row["Regular price"])


@pytest.mark.asyncio
async def test_html_sanitize_node_is_a_passthrough():
    assert await nodes.html_sanitize_node(_state()) == {}
