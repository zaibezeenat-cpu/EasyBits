from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.graph.nodes import duplicate_sku_guard_node, extractor_node
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.failure import FailureInfo
from app.models.raw_input import RawProductInput
from app.models.taxonomy import CategorySpecSchema, SpecField


@pytest.mark.asyncio
async def test_duplicate_sku_guard_node_new():
    # Mock repository
    mock_repo = MagicMock()
    mock_repo.exists = AsyncMock(return_value=False)

    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="NEW-SKU",
            model_number="M1",
            brand_name="B1",
            category_name="C1",
            product_type="T1",
            regular_price=Decimal(100),
            sale_price=Decimal(90)
        )
    )

    with patch("app.builders.sku_guard.sku_snapshot_repo", mock_repo):
        result = await duplicate_sku_guard_node(state)

    assert not result.get("manual_review_required", False)

@pytest.mark.asyncio
async def test_duplicate_sku_guard_node_duplicate():
    mock_repo = MagicMock()
    mock_repo.exists = AsyncMock(return_value=True)

    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="EXISTING-SKU",
            model_number="M1",
            brand_name="B1",
            category_name="C1",
            product_type="T1",
            regular_price=Decimal(100),
            sale_price=Decimal(90)
        )
    )

    with patch("app.builders.sku_guard.sku_snapshot_repo", mock_repo):
        result = await duplicate_sku_guard_node(state)

    assert result["manual_review_required"] is True

@pytest.mark.asyncio
async def test_extractor_node_no_urls_proceeds_with_zero_grounding():
    """
    2026-08-09 (owner-directed): finding no source at all (nothing discovered,
    nothing operator-provided) no longer escalates -- it proceeds with an
    empty source list, and the Extractor is expected to return every field
    UNKNOWN rather than invent one. Downstream this renders "Not Available",
    it does not block the product.
    """
    now = datetime.now(UTC)
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="SKU1",
            model_number="M1",
            brand_name="B1",
            category_name="C1",
            product_type="T1",
            regular_price=Decimal(100),
            sale_price=Decimal(90)
        ),
        category_schema=schema,
    )

    empty_extraction = ExtractionResult(product_id="p1", category_key="c1", citations=[])

    with patch("app.graph.nodes.scrape_product", AsyncMock(return_value={"failure": FailureInfo(category="no_reliable_source_found", detail="No reliable source found")})), \
         patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value=None)), \
         patch("app.graph.nodes.llm_provider.call", AsyncMock(return_value=empty_extraction)):
        result = await extractor_node(state)

    assert not result.get("manual_review_required", False)
    assert "failure" not in result
    assert result["extraction"].confirmed_value("capacity") is None


@pytest.mark.asyncio
async def test_extractor_node_always_confirms_brand_and_model_from_the_input_sheet():
    """
    Owner-reported (2026-08-12, live): a real product (AG-2098) showed
    brand and model_number as "Not Available" even though both are typed
    directly on the input sheet -- because scraping found nothing to
    corroborate them, and the Extractor LLM (correctly, per its
    no-hallucination contract) only cites what a SOURCE states.

    A previous fix (reviewer_node) papered over this for the Reviewer's own
    fact-check prompt only, by patching a local `facts` dict that nothing
    else ever reads. This is the real fix: inject brand/model_number as
    confirmed citations directly into the ExtractionResult itself, so
    confirmed_value("brand")/("model_number") is correct EVERYWHERE it's
    read -- the specs table, any diagnostic script, the Reviewer, all of it
    -- not just one prompt.

    source_type="user_estimate" (the lowest trust tier) so this only fills
    a gap -- it must never be able to outrank a genuinely scraped, higher-
    trust citation that disagrees with it.
    """
    now = datetime.now(UTC)
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="AG-2098", model_number="AG-2098", brand_name="Anex",
            category_name="Vacuum Cleaner", product_type="Vacuum Cleaner",
            regular_price=Decimal(28475), sale_price=Decimal(28475),
        ),
        category_schema=schema,
    )
    # Nothing scraped ever states brand/model -- the exact reported shape.
    empty_extraction = ExtractionResult(product_id="p1", category_key="c1", citations=[])
    scraped = {"scraped_data": [{
        "url": "https://anex.pk/ag-2098", "source_type": "official",
        "content": "Deluxe 2 in 1 vacuum cleaner, 1500W motor.",
        "candidate_titles": ["Anex AG-2098 Deluxe Vacuum Cleaner"],
    }]}

    with patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)), \
         patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value=None)), \
         patch("app.graph.nodes.llm_provider.call", AsyncMock(return_value=empty_extraction)):
        result = await extractor_node(state)

    extraction = result["extraction"]
    assert extraction.confirmed_value("brand") == "Anex"
    assert extraction.confirmed_value("model_number") == "AG-2098"
    # Never upgraded to a higher trust tier -- it's a fallback, not a claim
    # of independent verification.
    brand_citation = next(c for c in extraction.citations if c.field_name == "brand")
    assert brand_citation.source_type == "user_estimate"


@pytest.mark.asyncio
async def test_a_genuinely_scraped_brand_still_wins_over_the_operator_fallback():
    """
    The injected citation must never outrank a REAL, higher-trust citation
    the Extractor actually found -- it only fills a gap when nothing else
    confirmed the field.

    Review-flagged (2026-08-12): the first version of this test used the
    SAME value on both sides ("Anex" operator vs "Anex" scraped), so it
    would have passed trivially even if the tier logic were broken (e.g.
    if _operator_identity_citations mistakenly emitted source_type=
    "official"). The scraped value here is deliberately DIFFERENT from the
    operator's input, so the assertion can only pass if the tier ranking is
    genuinely correct.
    """
    now = datetime.now(UTC)
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(),
        raw_input=RawProductInput(
            # Deliberately a typo/stale value on the input sheet -- the
            # official site is the ground truth when the two disagree.
            sku="AG-2098", model_number="AG-2098", brand_name="Anex Pakistan",
            category_name="Vacuum Cleaner", product_type="Vacuum Cleaner",
            regular_price=Decimal(28475), sale_price=Decimal(28475),
        ),
        category_schema=schema,
    )
    scraped_extraction = ExtractionResult(
        product_id="p1", category_key="c1",
        citations=[SourceCitation(
            field_name="brand", value="Anex", source_url="https://anex.pk/ag-2098",
            source_type="official", confidence="confirmed", fetched_at=now,
        )],
    )
    scraped = {"scraped_data": [{
        "url": "https://anex.pk/ag-2098", "source_type": "official",
        "content": "Anex AG-2098", "candidate_titles": [],
    }]}

    with patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)), \
         patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value=None)), \
         patch("app.graph.nodes.llm_provider.call", AsyncMock(return_value=scraped_extraction)):
        result = await extractor_node(state)

    extraction = result["extraction"]
    assert extraction.confirmed_value("brand") == "Anex", (
        "the scraped official value must win over the operator's differing input"
    )
    brand_citations = [c for c in extraction.citations if c.field_name == "brand"]
    assert any(c.source_type == "official" and c.value == "Anex" for c in brand_citations)
    assert any(c.source_type == "user_estimate" and c.value == "Anex Pakistan" for c in brand_citations), (
        "the operator's citation must still be PRESENT (for QA visibility), just not winning"
    )


@pytest.mark.asyncio
async def test_pass_2_widening_does_not_duplicate_the_operator_citations():
    """
    The operator citations are injected after BOTH the initial and the
    Google-tier pass-2 extraction call -- confirms this doesn't duplicate
    them, since `extraction` is REASSIGNED (not appended to) at the pass-2
    call site, discarding the first call's injected citations along with
    the rest of that object.
    """
    now = datetime.now(UTC)
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="AG-2098", model_number="AG-2098", brand_name="Anex",
            category_name="Vacuum Cleaner", product_type="Vacuum Cleaner",
            regular_price=Decimal(28475), sale_price=Decimal(28475),
        ),
        category_schema=schema,
    )
    # First call finds nothing for capacity (triggers pass-2 widening);
    # second call (after Google-tier widening) finds it.
    first_pass = ExtractionResult(product_id="p1", category_key="c1", citations=[])
    second_pass = ExtractionResult(
        product_id="p1", category_key="c1",
        citations=[SourceCitation(
            field_name="capacity", value="5L", source_url="https://anex.pk/ag-2098",
            source_type="official", confidence="confirmed", fetched_at=now,
        )],
    )
    scraped = {"scraped_data": [{
        "url": "https://anex.pk/ag-2098", "source_type": "official",
        "content": "x", "candidate_titles": [],
    }]}

    with patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)), \
         patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value=None)), \
         patch("app.graph.nodes.google_search_client.api_key", "test-key"), \
         patch("app.graph.nodes.google_search_client.cx", "test-cx"), \
         patch("app.graph.nodes.llm_provider.call", AsyncMock(side_effect=[first_pass, second_pass])):
        result = await extractor_node(state)

    extraction = result["extraction"]
    brand_citations = [c for c in extraction.citations if c.field_name == "brand"]
    model_citations = [c for c in extraction.citations if c.field_name == "model_number"]
    assert len(brand_citations) == 1, f"expected exactly 1 brand citation, got {len(brand_citations)}"
    assert len(model_citations) == 1, f"expected exactly 1 model_number citation, got {len(model_citations)}"


@pytest.mark.asyncio
async def test_extractor_node_routes_trusted_secondary_titles_into_the_trusted_bucket():
    """
    2026-08-10 (owner-reported, review-flagged): the actual root-cause line
    for the "Handy"/"Deluxe" missing-title bug is this filter condition --
    it was `source_type == "official"` only; widened to also include
    `trusted_secondary`. Asserted directly against extractor_node's output
    (not just against a hand-built PipelineState downstream) so a future
    accidental revert of this one-line condition is actually caught.
    """
    now = datetime.now(UTC)
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="AG-12", model_number="AG-12", brand_name="Anex",
            category_name="Food Processor", product_type="Food Processor",
            regular_price=Decimal(5000), sale_price=Decimal(4500),
        ),
        category_schema=schema,
    )
    empty_extraction = ExtractionResult(product_id="p1", category_key="c1", citations=[])
    scraped = {"scraped_data": [
        {"url": "https://anex.pk/ag-12", "source_type": "official",
         "content": "x", "candidate_titles": ["Anex AG-12 Food Processor"]},
        {"url": "https://surmawala.pk/ag-12", "source_type": "trusted_secondary",
         "content": "x", "candidate_titles": ["Anex AG-12 Handy Food Processor"]},
        {"url": "https://someblog.pk/ag-12", "source_type": "web",
         "content": "x", "candidate_titles": ["Anex AG-12 Turbo Food Processor"]},
    ]}

    with patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)), \
         patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value=None)), \
         patch("app.graph.nodes.llm_provider.call", AsyncMock(return_value=empty_extraction)):
        result = await extractor_node(state)

    assert "Anex AG-12 Handy Food Processor" in result["trusted_titles"]
    assert "Anex AG-12 Turbo Food Processor" not in result["trusted_titles"], (
        "a web source must never enter the trusted bucket"
    )
    # competitor_titles is unchanged: ALL sources, trusted or not.
    assert "Anex AG-12 Turbo Food Processor" in result["competitor_titles"]


@pytest.mark.asyncio
async def test_strict_mode_still_discovers_when_no_operator_source_was_given():
    """
    Owner-reported (2026-08-12, live): a product produced "zero grounding --
    every spec field will render 'Not Available'" with NOT ONE fetch even
    attempted. Root cause: provided_source_mode="strict" skips discovery
    entirely, which is correct ONLY while an operator source actually
    exists to be strict about. With the sheet's Website Link column blank,
    strict mode silently meant "use no sources at all" -- so scraping, the
    platform JSON fast path and every title/spec fix downstream were all
    bypassed, and the product shipped with nothing verified.

    Strict must now mean "prefer the operator's source EXCLUSIVELY when
    there is one", never "ship blind when there isn't".
    """
    now = datetime.now(UTC)
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="AG-2098", model_number="AG-2098", brand_name="Anex",
            category_name="Vacuum Cleaner", product_type="Vacuum Cleaner",
            regular_price=Decimal(28475), sale_price=Decimal(28475),
        ),
        category_schema=schema,
    )
    empty_extraction = ExtractionResult(product_id="p1", category_key="c1", citations=[])
    discovered = {"scraped_data": [{
        "url": "https://www.anex.pk/products/ag-2098", "source_type": "official",
        "content": "Anex AG-2098 2 in 1 vacuum cleaner 1500W",
        "candidate_titles": ["Anex AG-2098 Deluxe 2 in 1 Vacuum Cleaner"],
    }]}
    scrape = AsyncMock(return_value=discovered)

    with patch("app.graph.nodes.scrape_product", scrape), \
         patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value="strict")), \
         patch("app.graph.nodes._build_operator_source_docs", AsyncMock(return_value=[])), \
         patch("app.graph.nodes.llm_provider.call", AsyncMock(return_value=empty_extraction)):
        result = await extractor_node(state)

    assert scrape.await_count >= 1, (
        "strict mode with NO operator source must still run discovery, "
        "not ship the product with zero grounding"
    )
    assert "Anex AG-2098 Deluxe 2 in 1 Vacuum Cleaner" in result["trusted_titles"]
