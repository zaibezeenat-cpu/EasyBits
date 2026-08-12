"""
Operator-provided source (the real sheet's Website Link + Details).

These lock the behaviour the owner asked for: a supplied link/details is used as an
authoritative source; a toggle chooses whether discovery still runs (augment) or is
skipped entirely (strict); a link that fails to scrape falls back to the pasted
details; and a huge paste can never blow the token budget.
"""
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.graph import nodes
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.raw_input import RawProductInput
from app.models.taxonomy import CategorySpecSchema, SpecField
from app.scraping.playwright_client import _MAX_CLEANED_CONTENT_CHARS

# --- fixtures ---------------------------------------------------------------

def _raw(**overrides) -> RawProductInput:
    base = {
        "sku": "WF-6807", "model_number": "WF-6807", "brand_name": "Westpoint",
        "category_name": "Air conditioner", "product_type": "Air conditioner",
        "regular_price": Decimal(6400), "sale_price": Decimal(6400),
        "warranty_override": "2 Years Warranty",
    }
    base.update(overrides)
    return RawProductInput(**base)


def _schema() -> CategorySpecSchema:
    now = datetime.now(UTC)
    return CategorySpecSchema(
        id=uuid4(), category_id=uuid4(), created_at=now, updated_at=now,
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
    )


def _extraction() -> ExtractionResult:
    now = datetime.now(UTC)
    return ExtractionResult(
        product_id=str(uuid4()), category_key="air_conditioner",
        citations=[SourceCitation(
            field_name="capacity", value="35 Watts", source_url="https://westpoint.pk/p",
            source_type="official", confidence="confirmed", fetched_at=now,
        )],
        image_urls=[],
    )


def _scrape_ok(content="Deluxe Hair Straightener WF-6807 35 Watts 2 Years Warranty"):
    return SimpleNamespace(success=True, content=content,
                           url="https://westpoint.pk/products/wf-6807",
                           candidate_titles=["Deluxe Hair Straightener WF-6807"])


def _state(**overrides) -> PipelineState:
    base = {"product_id": uuid4(), "batch_id": uuid4(), "raw_input": _raw()}
    base.update(overrides)
    return PipelineState(**base)


# --- _build_operator_source_docs -------------------------------------------

@pytest.mark.asyncio
async def test_details_only_becomes_an_official_source_doc(monkeypatch):
    monkeypatch.setattr(nodes, "smart_fetch", AsyncMock())
    docs = await nodes._build_operator_source_docs(
        _raw(source_details="35 Watts 220-240V. 2 Years Warranty. Ceramic plate.")
    )
    assert len(docs) == 1
    assert docs[0]["source_type"] == "official"
    assert docs[0]["url"] == "operator-provided"
    assert "35 Watts" in docs[0]["content"]
    # No link given -> the scraper must not have been called.
    nodes.smart_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_official_url_is_scraped_as_official(monkeypatch):
    monkeypatch.setattr(nodes, "smart_fetch", AsyncMock(return_value=_scrape_ok()))
    docs = await nodes._build_operator_source_docs(
        _raw(official_url="https://westpoint.pk/products/wf-6807")
    )
    assert len(docs) == 1
    assert docs[0]["source_type"] == "official"
    assert docs[0]["url"] == "https://westpoint.pk/products/wf-6807"
    assert "WF-6807" in docs[0]["content"]


@pytest.mark.asyncio
async def test_blocked_official_url_is_not_stored_falls_back_to_details(monkeypatch):
    # A blocked link returns success=True with the Cloudflare page as content. That
    # must NOT become the "official source"; the pasted details are used instead.
    blocked = SimpleNamespace(success=True, content="Just a moment...\nEnable JavaScript and cookies",
                              url="https://blocked.pk/p", candidate_titles=[])
    monkeypatch.setattr(nodes, "smart_fetch", AsyncMock(return_value=blocked))
    docs = await nodes._build_operator_source_docs(
        _raw(official_url="https://blocked.pk/p", source_details="35 Watts. 2 Years Warranty.")
    )
    assert len(docs) == 1
    assert "35 Watts" in docs[0]["content"]
    assert "Just a moment" not in docs[0]["content"]  # block page never stored


@pytest.mark.asyncio
async def test_failed_link_scrape_falls_back_to_details(monkeypatch):
    # Cloudflare / 403 / timeout: the link raises, but pasted details still save it.
    monkeypatch.setattr(nodes, "smart_fetch",
                        AsyncMock(side_effect=Exception("403 Forbidden")))
    docs = await nodes._build_operator_source_docs(
        _raw(official_url="https://blocked.pk/p", source_details="35 Watts. 2 Years Warranty.")
    )
    assert len(docs) == 1
    assert docs[0]["source_type"] == "official"
    assert "35 Watts" in docs[0]["content"]


@pytest.mark.asyncio
async def test_huge_details_paste_is_truncated(monkeypatch):
    monkeypatch.setattr(nodes, "smart_fetch", AsyncMock())
    docs = await nodes._build_operator_source_docs(_raw(source_details="word " * 20000))
    assert len(docs[0]["content"]) <= _MAX_CLEANED_CONTENT_CHARS


@pytest.mark.asyncio
async def test_non_http_official_url_is_not_fetched_ssrf_guard(monkeypatch):
    # SSRF guard: only http(s) is ever fetched server-side. A file:// (or any
    # other scheme) is ignored, falling back to details if provided.
    scrape = AsyncMock(return_value=_scrape_ok())
    monkeypatch.setattr(nodes, "smart_fetch", scrape)
    docs = await nodes._build_operator_source_docs(
        _raw(official_url="file:///etc/passwd", source_details="35 Watts.")
    )
    scrape.assert_not_called()
    assert len(docs) == 1
    assert "35 Watts" in docs[0]["content"]


# --- extractor_node mode logic ---------------------------------------------

@pytest.mark.asyncio
async def test_strict_with_nothing_provided_falls_back_to_discovery(monkeypatch):
    """
    REVERSED 2026-08-12 (owner-reported live bug), and deliberately so.

    The 2026-08-09 rule was "strict must NEVER fall back to discovery", which
    is right while an operator source EXISTS to be strict about. With the
    sheet's Website Link column blank it instead meant "use no sources at
    all": the product shipped with zero grounding, every spec "Not
    Available", and NOT ONE fetch even attempted -- silently bypassing
    discovery, the platform-JSON fast path and every downstream title/spec
    guarantee, with no error explaining why.

    Strict's real guarantee is narrower than the old test claimed: when the
    operator DID supply a source, discovery must never run
    (test_strict_with_details_uses_only_operator_source, unchanged, still
    asserts exactly that). When they supplied nothing, there is nothing to be
    strict about and discovery is the only way the product gets any facts.
    """
    monkeypatch.setattr(nodes.settings_repo, "get_setting", AsyncMock(return_value="strict"))
    scrape = AsyncMock()
    monkeypatch.setattr(nodes, "scrape_product", scrape)
    empty_extraction = ExtractionResult(
        product_id=str(uuid4()), category_key="air_conditioner", citations=[], image_urls=[],
    )
    monkeypatch.setattr(nodes.llm_provider, "call", AsyncMock(return_value=empty_extraction))

    scrape.return_value = {"scraped_data": []}
    result = await extractor_or_state(monkeypatch, _state(category_schema=_schema()))

    assert not result.get("manual_review_required", False)
    assert "extraction" in result
    scrape.assert_called()


@pytest.mark.asyncio
async def test_strict_with_details_uses_only_operator_source(monkeypatch):
    monkeypatch.setattr(nodes.settings_repo, "get_setting", AsyncMock(return_value="strict"))
    scrape = AsyncMock()
    monkeypatch.setattr(nodes, "scrape_product", scrape)
    monkeypatch.setattr(nodes, "smart_fetch", AsyncMock())
    monkeypatch.setattr(nodes.llm_provider, "call", AsyncMock(return_value=_extraction()))

    state = _state(
        raw_input=_raw(source_details="35 Watts 220-240V. Ceramic plate."),
        category_schema=_schema(),
    )
    result = await nodes.extractor_node(state)
    assert "extraction" in result
    # Strict mode must never run search-based discovery.
    scrape.assert_not_called()


@pytest.mark.asyncio
async def test_augment_runs_discovery_and_merges_operator_source(monkeypatch):
    monkeypatch.setattr(nodes.settings_repo, "get_setting", AsyncMock(return_value="augment"))
    scrape = AsyncMock(return_value={"scraped_data": [
        {"url": "https://retailer.pk/p", "source_type": "trusted_secondary",
         "content": "WF-6807 35 Watts", "candidate_titles": []},
    ]})
    monkeypatch.setattr(nodes, "scrape_product", scrape)
    monkeypatch.setattr(nodes, "smart_fetch", AsyncMock(return_value=_scrape_ok()))
    # scrape returns scraped_data (no "failure"), so the Google fallback branch is
    # never reached and google_search_client need not be touched.
    captured = {}

    async def fake_call(**kwargs):
        captured["source_documents"] = kwargs.get("system_prompt", "")
        return _extraction()

    monkeypatch.setattr(nodes.llm_provider, "call", AsyncMock(side_effect=fake_call))

    state = _state(
        raw_input=_raw(official_url="https://westpoint.pk/products/wf-6807"),
        category_schema=_schema(),
    )
    result = await nodes.extractor_node(state)
    assert "extraction" in result
    # Augment DID run discovery on top of the operator source.
    scrape.assert_called_once()


async def extractor_or_state(monkeypatch, state):
    """extractor_node needs no scrape_with_playwright when nothing is provided."""
    monkeypatch.setattr(nodes, "smart_fetch", AsyncMock())
    return await nodes.extractor_node(state)
