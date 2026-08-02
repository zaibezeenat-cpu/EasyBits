"""
Tests for LLM cost estimation and the monthly budget cap.

Context: the budget guard was decorative. `llm_provider.call()` never wrote
`estimated_cost_usd`, so `get_monthly_spend()` always summed to 0 and
`check_budget_ok()` could never return False no matter how much was spent. These
tests lock both halves: that a cost is actually computed, and that the cap
actually stops a batch.
"""
import pytest

from app.core import budget_guard
from app.core.llm_provider import _extract_token_usage, estimate_cost_usd


# --- Cost estimation --------------------------------------------------------

def test_cost_is_computed_from_real_token_counts():
    """Groq llama-3.3-70b at $0.59/1M input, $0.79/1M output."""
    cost = estimate_cost_usd("groq", "llama-3.3-70b-versatile", 547, 621)
    expected = (547 * 0.59 + 621 * 0.79) / 1_000_000
    assert cost == pytest.approx(expected)
    assert cost > 0, "a real call must never record zero cost for a priced model"


def test_unknown_model_costs_zero_rather_than_crashing():
    """
    An unpriced model must not raise mid-pipeline. Zero is recorded so the row
    still exists and the gap is visible, rather than losing the call entirely.
    """
    assert estimate_cost_usd("groq", "some-new-model", 1000, 1000) == 0.0


def test_zero_tokens_cost_zero():
    assert estimate_cost_usd("groq", "llama-3.3-70b-versatile", 0, 0) == 0.0


# --- Token extraction -------------------------------------------------------

class _FakeMessage:
    def __init__(self, usage_metadata=None, response_metadata=None):
        if usage_metadata is not None:
            self.usage_metadata = usage_metadata
        if response_metadata is not None:
            self.response_metadata = response_metadata


def test_extracts_tokens_from_usage_metadata():
    msg = _FakeMessage(usage_metadata={"input_tokens": 547, "output_tokens": 621})
    assert _extract_token_usage(msg) == (547, 621)


def test_extracts_tokens_from_response_metadata_fallback():
    msg = _FakeMessage(response_metadata={"token_usage": {"prompt_tokens": 100, "completion_tokens": 200}})
    assert _extract_token_usage(msg) == (100, 200)


def test_missing_usage_data_returns_zeros_not_a_guess():
    """
    An unknown token count must never be invented -- a fabricated cost would
    either trip the cap early or hide real spend.
    """
    assert _extract_token_usage(_FakeMessage()) == (0, 0)
    assert _extract_token_usage(None) == (0, 0)


# --- Budget cap -------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_allows_spend_below_cap(monkeypatch):
    async def fake_setting(_key):
        return 5.00

    async def fake_spend():
        return 2.50

    monkeypatch.setattr(budget_guard.settings_repo, "get_setting", fake_setting)
    monkeypatch.setattr(budget_guard.llm_usage_repo, "get_monthly_spend", fake_spend)
    assert await budget_guard.check_budget_ok() is True


@pytest.mark.asyncio
async def test_budget_blocks_when_cap_reached(monkeypatch):
    """The core guarantee that was previously impossible to satisfy."""
    async def fake_setting(_key):
        return 5.00

    async def fake_spend():
        return 5.00

    monkeypatch.setattr(budget_guard.settings_repo, "get_setting", fake_setting)
    monkeypatch.setattr(budget_guard.llm_usage_repo, "get_monthly_spend", fake_spend)
    assert await budget_guard.check_budget_ok() is False


@pytest.mark.asyncio
async def test_budget_blocks_when_cap_exceeded(monkeypatch):
    async def fake_setting(_key):
        return 5.00

    async def fake_spend():
        return 7.31

    monkeypatch.setattr(budget_guard.settings_repo, "get_setting", fake_setting)
    monkeypatch.setattr(budget_guard.llm_usage_repo, "get_monthly_spend", fake_spend)
    assert await budget_guard.check_budget_ok() is False


@pytest.mark.asyncio
async def test_budget_defaults_to_five_dollars_when_unset(monkeypatch):
    """Missing setting must not mean 'unlimited'."""
    async def fake_setting(_key):
        return None

    async def fake_spend():
        return 6.00

    monkeypatch.setattr(budget_guard.settings_repo, "get_setting", fake_setting)
    monkeypatch.setattr(budget_guard.llm_usage_repo, "get_monthly_spend", fake_spend)
    assert await budget_guard.check_budget_ok() is False
