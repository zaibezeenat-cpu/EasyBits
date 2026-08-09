"""
The two speed/safety changes to llm_provider.py for BATCH_CONCURRENCY > 1:

1. A provider-global semaphore (MAX_CONCURRENT_LLM_CALLS_PER_PROVIDER) so N
   concurrent products don't turn into N simultaneous requests at one
   provider -- shared across ALL roles, since Writer/Reviewer's fallback is
   also the Extractor's primary (see llm_provider.py's ROLE_MODEL_CONFIG).
2. One same-provider retry with backoff on anything that looks like a 429,
   before falling to the configured fallback provider.

No real API calls: the langchain model is monkeypatched out entirely, so
these prove the provider's own control flow, not third-party behaviour.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from app.core.llm_provider import LLMProvider, _looks_like_rate_limit


class _Out(BaseModel):
    value: str = "ok"


def _fake_model(structured_llm) -> MagicMock:
    model = MagicMock()
    model.with_structured_output.return_value = structured_llm
    return model


def _envelope(value: str = "ok") -> dict:
    return {"parsed": _Out(value=value), "parsing_error": None, "raw": MagicMock(usage_metadata=None, response_metadata=None)}


@pytest.mark.parametrize("message", [
    "429 Too Many Requests", "Rate limit reached", "RESOURCE_EXHAUSTED", "quota exceeded",
])
def test_rate_limit_detection_matches_real_provider_wording(message):
    assert _looks_like_rate_limit(Exception(message))


def test_unrelated_error_is_not_treated_as_a_rate_limit():
    assert not _looks_like_rate_limit(Exception("Connection reset by peer"))


@pytest.mark.asyncio
async def test_a_429_retries_the_same_provider_before_falling_back(monkeypatch):
    """
    Primary provider (google) 429s once, then succeeds on retry -- the
    fallback provider (groq) must never be touched.
    """
    provider = LLMProvider()
    monkeypatch.setattr("app.core.llm_provider.llm_usage_repo.log_usage", AsyncMock())
    monkeypatch.setattr("app.core.llm_provider.asyncio.sleep", AsyncMock())

    calls = {"google": 0, "groq": 0}

    def build_model(self, provider_name, model_name):
        structured = MagicMock()

        async def ainvoke(messages):
            calls[provider_name] += 1
            if provider_name == "google" and calls[provider_name] == 1:
                raise Exception("429 rate limit exceeded")
            return _envelope()

        structured.ainvoke = ainvoke
        return _fake_model(structured)

    monkeypatch.setattr(LLMProvider, "_build_model", build_model)

    result = await provider.call(
        role="extractor", system_prompt="s", human_prompt="h", response_model=_Out,
    )
    assert result.value == "ok"
    assert calls["google"] == 2, "must retry google once before giving up on it"
    assert calls["groq"] == 0, "must never touch the fallback provider"


@pytest.mark.asyncio
async def test_a_non_rate_limit_error_falls_back_immediately_without_a_retry(monkeypatch):
    """A non-429 failure should NOT get the extra same-provider retry -- go
    straight to the fallback provider, same as before this change."""
    provider = LLMProvider()
    monkeypatch.setattr("app.core.llm_provider.llm_usage_repo.log_usage", AsyncMock())
    monkeypatch.setattr("app.core.llm_provider.asyncio.sleep", AsyncMock())

    calls = {"google": 0, "groq": 0}

    def build_model(self, provider_name, model_name):
        structured = MagicMock()

        async def ainvoke(messages):
            calls[provider_name] += 1
            if provider_name == "google":
                raise Exception("model did not call a tool")
            return _envelope()

        structured.ainvoke = ainvoke
        return _fake_model(structured)

    monkeypatch.setattr(LLMProvider, "_build_model", build_model)

    result = await provider.call(
        role="extractor", system_prompt="s", human_prompt="h", response_model=_Out,
    )
    assert result.value == "ok"
    assert calls["google"] == 1, "no retry for a non-rate-limit error"
    assert calls["groq"] == 1


@pytest.mark.asyncio
async def test_provider_semaphore_caps_concurrent_in_flight_calls(monkeypatch):
    """
    With MAX_CONCURRENT_LLM_CALLS_PER_PROVIDER=1, two concurrent calls to the
    SAME provider must be serialised -- the second cannot start its ainvoke
    until the first has released the semaphore.
    """
    monkeypatch.setattr("app.core.llm_provider.settings.MAX_CONCURRENT_LLM_CALLS_PER_PROVIDER", 1)
    provider = LLMProvider()
    monkeypatch.setattr("app.core.llm_provider.llm_usage_repo.log_usage", AsyncMock())

    concurrent_count = 0
    max_concurrent = 0

    def build_model(self, provider_name, model_name):
        structured = MagicMock()

        async def ainvoke(messages):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return _envelope()

        structured.ainvoke = ainvoke
        return _fake_model(structured)

    monkeypatch.setattr(LLMProvider, "_build_model", build_model)

    await asyncio.gather(
        provider.call(role="extractor", system_prompt="s", human_prompt="h", response_model=_Out),
        provider.call(role="categorizer", system_prompt="s", human_prompt="h", response_model=_Out),
    )
    assert max_concurrent == 1, "the provider semaphore must serialise same-provider calls"
