"""
The inference path, exercised through the real extractor_node.

WHY THIS EXISTS
---------------
The unit tests prove each piece in isolation: the citation contract, the
corroboration status, the schema flag, the enforcement filter. What they cannot
prove is that the pieces are actually WIRED together -- that `extractor_node`
really calls `drop_disallowed_inferences`, that a deduced field really stops
appearing in `missing`, that a product with a deduced spec really escapes
Manual Review.

That wiring is where the previous attempt failed. `CORE_FIELDS` was a correct
idea connected to the wrong names, and every unit around it passed.

Everything external is faked -- the LLM, the scraper, the database -- so this
runs offline with no credentials, no browser, and no network. It cannot tell us
how a real model behaves; it tells us the pipeline does the right thing with a
given extraction, which is the part we control.
"""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.graph.nodes import extractor_node
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.raw_input import RawProductInput
from app.models.taxonomy import CategorySpecSchema, SpecField

NOW = datetime.now(UTC)

# A vacuum whose listing describes a canister without ever using the word, and
# whose wattage no source states. The exact shape that used to be blocked.
SOURCE_TEXT = (
    "Anex AG-2095 Vacuum Cleaner. Comes with a flexible hose, extension tube "
    "and a big dust bag. 2 years warranty."
)


def _schema(*fields: SpecField) -> CategorySpecSchema:
    return CategorySpecSchema(
        id=uuid4(), category_id=uuid4(), fields=list(fields),
        created_at=NOW, updated_at=NOW,
    )


def _state(schema: CategorySpecSchema) -> PipelineState:
    return PipelineState(
        product_id=uuid4(), batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="AG-2095", model_number="AG-2095", brand_name="Anex",
            category_name="Vacuum Cleaner", product_type="Vacuum Cleaner",
            regular_price=Decimal(9000), sale_price=Decimal(7500),
            warranty_override="2 Years Warranty",
        ),
        category_schema=schema,
    )


def _cite(field: str, value: str, confidence: str = "confirmed", quote: str | None = None):
    return SourceCitation(
        field_name=field, value=value, source_url="https://anex.pk/ag-2095",
        source_type="official", confidence=confidence, fetched_at=NOW,
        exact_quote=quote,
    )


async def _run(schema: CategorySpecSchema, citations: list[SourceCitation]) -> dict:
    """Runs extractor_node with the LLM, scraper and DB all faked."""
    extraction = ExtractionResult(
        product_id="p1", category_key="vacuum", citations=citations,
        image_urls=["https://anex.pk/1.jpg"] * 3,
    )
    scraped = {"scraped_data": [{
        "url": "https://anex.pk/ag-2095", "source_type": "official",
        "content": SOURCE_TEXT, "candidate_titles": ["Anex AG-2095 Vacuum Cleaner"],
    }]}

    with (
        patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value="augment")),
        patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)),
        patch("app.graph.nodes._build_operator_source_docs", AsyncMock(return_value=[])),
        patch("app.graph.nodes.llm_provider.call", AsyncMock(return_value=extraction)),
        patch("app.graph.nodes.google_search_client") as gs,
    ):
        gs.configured = False
        return await extractor_node(_state(schema))


VACUUM_TYPE_INFERABLE = SpecField(
    key="vacuum_type", label="Vacuum Type", required=True, inferable=True
)
WATTAGE_STRICT = SpecField(key="wattage", label="Wattage", required=True)


@pytest.mark.asyncio
async def test_a_deduced_spec_lets_the_product_through():
    """
    THE HEADLINE CASE. No source prints "canister", but the features say so. The
    product must reach the writer instead of Manual Review.
    """
    result = await _run(
        _schema(VACUUM_TYPE_INFERABLE),
        [_cite("vacuum_type", "Canister", "inferred",
               "flexible hose, extension tube and a big dust bag")],
    )

    assert not result.get("manual_review_required"), (
        f"blocked despite a permitted deduction: {result.get('failure')}"
    )
    assert result["extraction"].inferred_value("vacuum_type") == "Canister"


@pytest.mark.asyncio
async def test_the_deduction_never_counts_as_a_verified_fact():
    """It ships, but it must not be indistinguishable from something a source said."""
    result = await _run(
        _schema(VACUUM_TYPE_INFERABLE),
        [_cite("vacuum_type", "Canister", "inferred", "flexible hose and dust bag")],
    )
    extraction = result["extraction"]

    assert extraction.confirmed_value("vacuum_type") is None
    assert not extraction.resolve("vacuum_type").is_confirmed


@pytest.mark.asyncio
async def test_a_deduced_measurement_is_stripped_and_still_blocks():
    """
    The model ignoring the prompt is the case that matters -- code has to catch
    it. A guessed wattage must be discarded AND must still stop the product.
    """
    result = await _run(
        _schema(VACUUM_TYPE_INFERABLE, WATTAGE_STRICT),
        [
            _cite("vacuum_type", "Canister", "inferred", "flexible hose, dust bag"),
            _cite("wattage", "1800 W", "inferred", "powerful suction motor"),
        ],
    )

    assert result.get("manual_review_required") is True
    assert "wattage" in result["failure"].detail
    assert result["extraction"].inferred_value("wattage") is None, "a guessed number survived"


@pytest.mark.asyncio
async def test_an_absent_required_field_still_blocks_when_not_inferable():
    """The old behaviour, unchanged: no source, no deduction, no ship."""
    result = await _run(_schema(WATTAGE_STRICT), [])

    assert result.get("manual_review_required") is True
    assert "wattage" in result["failure"].detail


@pytest.mark.asyncio
async def test_an_optional_field_does_not_block():
    """The manual-chopper fix, end to end: mark it not-required and it ships."""
    result = await _run(
        _schema(SpecField(key="wattage", label="Wattage", required=False)), []
    )
    assert not result.get("manual_review_required")


@pytest.mark.asyncio
async def test_a_stated_value_is_preferred_over_a_deduction():
    result = await _run(
        _schema(VACUUM_TYPE_INFERABLE),
        [
            _cite("vacuum_type", "Drum"),
            _cite("vacuum_type", "Canister", "inferred", "flexible hose"),
        ],
    )
    extraction = result["extraction"]

    assert extraction.confirmed_value("vacuum_type") == "Drum"
    assert extraction.resolve("vacuum_type").is_confirmed


@pytest.mark.asyncio
async def test_the_prompt_advertises_only_the_inferable_fields():
    """
    The model must never be shown a measurement as deducible. Asserted on the
    prompt actually sent, not on the template -- the two call sites fill it
    separately and one was missed the first time.
    """
    captured: dict = {}

    async def _capture(role, system_prompt, human_prompt, response_model):
        captured["prompt"] = system_prompt
        return ExtractionResult(
            product_id="p1", category_key="vacuum",
            citations=[_cite("vacuum_type", "Canister", "inferred", "hose, dust bag")],
        )

    scraped = {"scraped_data": [{
        "url": "https://anex.pk/x", "source_type": "official",
        "content": SOURCE_TEXT, "candidate_titles": [],
    }]}
    with (
        patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value="augment")),
        patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)),
        patch("app.graph.nodes._build_operator_source_docs", AsyncMock(return_value=[])),
        patch("app.graph.nodes.llm_provider.call", _capture),
        patch("app.graph.nodes.google_search_client") as gs,
    ):
        gs.configured = False
        await extractor_node(_state(_schema(VACUUM_TYPE_INFERABLE, WATTAGE_STRICT)))

    prompt = captured["prompt"]
    assert "{inferable_fields_json}" not in prompt, "placeholder reached the model unfilled"

    # Assert on the rendered JSON array itself, not on a slice of prose.
    #
    # An earlier version of this test sliced between "INFERABLE FIELDS" and
    # "Hard Rules" -- but the phrase appears six times in the prompt, so the
    # slice started at the first PROSE mention and never reached the list. The
    # assertion passed no matter what was injected. Mutation testing caught it:
    # widening the list to every field did not fail the test.
    #
    # The list is dumped as JSON, so the exact array is unambiguous. With only
    # vacuum_type inferable it must be exactly ["vacuum_type"]; if wattage ever
    # leaks in, that literal disappears and this fails.
    assert '["vacuum_type"]' in prompt, (
        "the inferable list is not exactly ['vacuum_type'] -- a non-inferable "
        "field is being offered to the model as deducible"
    )

    # And the full field list IS still supplied separately, so the two are not
    # accidentally the same value.
    assert '["vacuum_type", "wattage"]' in prompt, "required_fields_json is missing"
