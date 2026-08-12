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


def _cite(
    field: str, value: str, confidence: str = "confirmed", quote: str | None = None,
    source_type: str = "official",
):
    return SourceCitation(
        field_name=field, value=value, source_url="https://anex.pk/ag-2095",
        source_type=source_type, confidence=confidence, fetched_at=NOW,
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


async def _run_forcing_pass2(schema: CategorySpecSchema, pass1_citations, pass2_citations) -> dict:
    """
    Like `_run`, but actually exercises the PASS-2 (Google-tier) retry --
    `_run`'s google_search_client.configured=False always skips it, which
    left `_seed_known_facts`'s second call site (extractor_node's pass-2
    branch) with zero coverage (review-flagged). Forces pass 2 by leaving a
    required field (wattage) uncited in pass 1, so `missing` is non-empty and
    the retry fires; pass 1 and pass 2 return DISTINCT ExtractionResult
    objects, matching real production (pydantic constructs a fresh instance
    per LLM call), so this also proves the two seed calls don't compound into
    duplicate citations on one shared object.
    """
    extraction_pass1 = ExtractionResult(product_id="p1", category_key="vacuum", citations=pass1_citations)
    extraction_pass2 = ExtractionResult(product_id="p1", category_key="vacuum", citations=pass2_citations)
    responses = iter([extraction_pass1, extraction_pass2])

    async def _llm_call(role, system_prompt, human_prompt, response_model):
        return next(responses)

    scraped = {"scraped_data": [{
        "url": "https://anex.pk/ag-2095", "source_type": "official",
        "content": SOURCE_TEXT, "candidate_titles": ["Anex AG-2095 Vacuum Cleaner"],
    }]}
    extra_scraped = {"scraped_data": [{
        "url": "https://anex.pk/ag-2095-2", "source_type": "trusted_secondary",
        "content": SOURCE_TEXT, "candidate_titles": ["Anex AG-2095 Vacuum Cleaner"],
    }]}

    with (
        patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value="augment")),
        patch("app.graph.nodes.scrape_product", AsyncMock(side_effect=[scraped, extra_scraped])),
        patch("app.graph.nodes._build_operator_source_docs", AsyncMock(return_value=[])),
        patch("app.graph.nodes.llm_provider.call", _llm_call),
        patch("app.graph.nodes.google_search_client") as gs,
    ):
        gs.configured = True
        return await extractor_node(_state(schema))


@pytest.mark.asyncio
async def test_pass_2_retry_does_not_duplicate_seeded_citations():
    """The wattage gap forces PASS 2 to fire on a fresh ExtractionResult
    object; brand must still resolve cleanly, seeded exactly once per pass,
    not accumulated across both."""
    schema = _schema(BRAND_FIELD, WATTAGE_STRICT)
    result = await _run_forcing_pass2(schema, pass1_citations=[], pass2_citations=[])

    extraction = result["extraction"]
    brand_citations = [c for c in extraction.citations if c.field_name == "brand"]
    assert len(brand_citations) == 1, (
        f"expected exactly one seeded brand citation on the pass-2 object, "
        f"got {len(brand_citations)}"
    )
    assert extraction.confirmed_value("brand") == "Anex"


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
async def test_a_deduced_measurement_is_stripped_but_no_longer_blocks():
    """
    The model ignoring the prompt is the case that matters -- code has to catch
    it. A guessed wattage must still be discarded (enforcement is unchanged),
    but as of 2026-08-09 a field left missing after the strip no longer stops
    the product -- see extractor_node's note next to `if missing:`. It ships
    with wattage rendered "Not Available" instead of escalating.
    """
    result = await _run(
        _schema(VACUUM_TYPE_INFERABLE, WATTAGE_STRICT),
        [
            _cite("vacuum_type", "Canister", "inferred", "flexible hose, dust bag"),
            _cite("wattage", "1800 W", "inferred", "powerful suction motor"),
        ],
    )

    assert not result.get("manual_review_required")
    assert result["extraction"].inferred_value("wattage") is None, "a guessed number survived"


@pytest.mark.asyncio
async def test_an_absent_required_field_no_longer_blocks_when_not_inferable():
    """
    2026-08-09 (owner-directed): a required field no source states, and that
    cannot be deduced either, is skipped -- not escalated. It renders "Not
    Available" downstream (specs_renderer already tolerates a None
    confirmed_value). Only a genuine cross-source conflict still blocks.
    """
    schema = _schema(WATTAGE_STRICT)
    result = await _run(schema, [])

    assert not result.get("manual_review_required")
    assert result["extraction"].confirmed_value("wattage") is None
    assert "wattage" in result["extraction"].missing_required_fields(schema)


@pytest.mark.asyncio
async def test_an_optional_field_does_not_block():
    """The manual-chopper fix, end to end: mark it not-required and it ships."""
    result = await _run(
        _schema(SpecField(key="wattage", label="Wattage", required=False)), []
    )
    assert not result.get("manual_review_required")


# --- Brand / model number are raw_input, not extraction (2026-08-12) -------
#
# Owner-reported (AG-2098): "No source stated ['brand', 'model_number',
# 'vacuum_type'] for AG-2098" -- despite both being plainly typed into the
# input CSV ("Anex", "AG-2098"). brand and model_number are schema-required
# fields like any other spec, so `confirmed_value` returned None whenever no
# scraped page happened to restate them verbatim -- a category error: these
# two are never "extracted", they are the operator's own input, already
# known with certainty before scraping even runs.

BRAND_FIELD = SpecField(key="brand", label="Brand", required=True)
MODEL_NUMBER_FIELD = SpecField(key="model_number", label="Model Number", required=True)


@pytest.mark.asyncio
async def test_brand_and_model_number_are_confirmed_from_raw_input_alone():
    """No source states either field -- they still must not be missing."""
    schema = _schema(BRAND_FIELD, MODEL_NUMBER_FIELD)
    result = await _run(schema, [])  # zero citations: no source mentions either

    extraction = result["extraction"]
    assert extraction.confirmed_value("brand") == "Anex", (
        "brand is a CSV column (raw_input.brand_name), not something a "
        "source has to state"
    )
    assert extraction.confirmed_value("model_number") == "AG-2095"
    assert "brand" not in extraction.missing_required_fields(schema)
    assert "model_number" not in extraction.missing_required_fields(schema)
    assert not result.get("manual_review_required")


@pytest.mark.asyncio
async def test_a_source_agreeing_with_raw_input_brand_still_confirms():
    """A source stating the SAME brand must not create a false conflict."""
    schema = _schema(BRAND_FIELD)
    result = await _run(schema, [_cite("brand", "Anex")])
    assert result["extraction"].confirmed_value("brand") == "Anex"
    assert not result.get("manual_review_required")


@pytest.mark.asyncio
async def test_a_source_genuinely_disagreeing_with_raw_input_brand_still_conflicts():
    """
    An EQUALLY-trusted (official-tier) disagreement must still surface as a
    real conflict rather than being silently overridden -- the existing
    cross-source conflict logic in fact_corroboration.py must still see both
    sides when neither outranks the other.
    """
    schema = _schema(BRAND_FIELD)
    result = await _run(schema, [_cite("brand", "Totally Different Brand", source_type="official")])
    assert result.get("manual_review_required"), (
        "a genuine brand disagreement between raw_input and an equally-trusted "
        "scraped source must still escalate, not be silently decided by "
        "raw_input alone"
    )
    assert result["failure"].category == "spec_conflict"


@pytest.mark.asyncio
async def test_a_lower_trust_disagreement_loses_to_raw_input_without_escalating():
    """
    A trusted_secondary/web source disagreeing with raw_input does NOT tie or
    escalate -- official already outranks those tiers everywhere else in this
    system ("an official source outranking a lone retailer is a resolution,
    not a conflict"), and raw_input is resolved the same way, intentionally
    (see _seed_known_facts's docstring): a single lower-trust page naming a
    different brand for this exact SKU is far more likely to be a mismatched
    search result than the operator's own CSV being wrong.
    """
    schema = _schema(BRAND_FIELD)
    result = await _run(
        schema, [_cite("brand", "Totally Different Brand", source_type="web")]
    )
    assert result["extraction"].confirmed_value("brand") == "Anex", (
        "raw_input must win over an unvetted lower-tier disagreement, not "
        "escalate or be silently overridden by the weaker source"
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
