import logging
from datetime import datetime
from typing import Type, TypeVar
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.config import settings
from app.db.repositories.llm_usage import llm_usage_repo

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# phase1.md §4: Extractor -> Gemini (cheap/fast structured extraction).
# Writer/Reviewer -> Groq (free-tier, fast, avoids paying premium-model prices
# for the harder/more creative half of the job). One fallback per role, per
# phase1.md §4's explicit "single-provider dependency is a single point of
# failure" requirement.
#
# BUG FIX (V3.0 review): every node called llm_provider.call(role=..., ...)
# without ever passing model_id, so ALL THREE roles silently defaulted to the
# same hardcoded "gemini-pro" model. Writer and Reviewer were never actually
# reaching Groq -- defeating the free-tier cost design and creating exactly
# the single-provider dependency the spec warned against. Fixed by making
# `role` the actual routing key, not just a logging label.
# Model IDs verified by actually invoking each one with structured output
# against the real API keys (probe run 2026-07-21) -- not taken from docs or
# from list_models(), both of which proved unreliable here:
#
#   gemini-2.5-flash-lite    404s ("no longer available to new users") despite
#                            being listed by Google's own list_models().
#   gemini-flash-lite-latest OK -- Google's rolling alias.
#   openai/gpt-oss-120b      FAILS 100% of calls ("model did not call a tool" /
#                            "failed to parse tool call arguments"). This was
#                            the Writer+Reviewer primary, so every single call
#                            silently fell back to Gemini and the free-tier cost
#                            design never actually ran.
#   llama-3.3-70b-versatile  OK -- honours the strict WriterOutput schema
#                            (exactly 5 FAQs, exactly 3 LSI keywords).
#   llama-3.1-8b-instant     Returns schema violations (4 LSI keywords instead
#                            of 3). Removed as the Extractor fallback: a
#                            fallback that breaks the contract is worse than no
#                            fallback, because it fails deep in validation
#                            instead of at the call boundary.
ROLE_MODEL_CONFIG: dict[str, dict[str, str]] = {
    "extractor": {"primary_provider": "google", "primary_model": "gemini-flash-lite-latest",
                  "fallback_provider": "groq", "fallback_model": "llama-3.3-70b-versatile"},
    "writer": {"primary_provider": "groq", "primary_model": "llama-3.3-70b-versatile",
               "fallback_provider": "google", "fallback_model": "gemini-flash-lite-latest"},
    "reviewer": {"primary_provider": "groq", "primary_model": "llama-3.3-70b-versatile",
                 "fallback_provider": "google", "fallback_model": "gemini-flash-lite-latest"},
    # Category classifier: a tiny "pick one from this exact list or UNKNOWN" call,
    # used ONLY when deterministic name-matching finds nothing (e.g. a hair
    # straightener -> "Beauty", whose name never appears in the product title).
    # Cheapest capable model; Groq fallback if Gemini is down.
    "categorizer": {"primary_provider": "google", "primary_model": "gemini-flash-lite-latest",
                    "fallback_provider": "groq", "fallback_model": "llama-3.3-70b-versatile"},
}

# USD per 1M tokens, per provider+model. Used to populate
# llm_usage_log.estimated_cost_usd so the monthly budget cap can actually work.
# Free-tier models are recorded as 0.0 rather than omitted -- a zero cost is a
# real measurement, whereas a missing row makes spend unknowable.
MODEL_PRICING_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    "google:gemini-flash-lite-latest": {"input": 0.10, "output": 0.40},
    "groq:llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "groq:llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
}
DEFAULT_PRICING = {"input": 0.0, "output": 0.0}

# Per-call ceiling. Generous enough for a long Writer generation, short enough
# that a stalled provider fails over to the fallback instead of blocking the
# batch. `max_retries=1` on top of this keeps one transient blip from wasting
# the whole budget on retries of a provider that is genuinely down.
LLM_TIMEOUT_SECONDS = 120


def estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Converts token usage into a USD estimate for the budget guard.

    Called "estimate" deliberately: published per-token rates change and the
    token counts come from the provider's own response metadata, so this tracks
    spend closely enough to enforce a cap without pretending to be an invoice.
    """
    pricing = MODEL_PRICING_PER_1M_TOKENS.get(f"{provider}:{model}", DEFAULT_PRICING)
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def _extract_token_usage(result: object) -> tuple[int, int]:
    """
    Pulls (input_tokens, output_tokens) from a LangChain result.

    with_structured_output() returns the parsed Pydantic model, which carries no
    usage metadata, so this reads it from `usage_metadata`/`response_metadata`
    when the provider surfaced it and returns (0, 0) otherwise. Returning zeros
    is deliberate: an unknown cost must never be invented, and a run of
    zero-cost rows is a visible signal that usage reporting needs attention.
    """
    usage = getattr(result, "usage_metadata", None)
    if isinstance(usage, dict):
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))

    meta = getattr(result, "response_metadata", None)
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict):
            return (
                int(token_usage.get("prompt_tokens", 0)),
                int(token_usage.get("completion_tokens", 0)),
            )
    return 0, 0


class LLMProvider:
    def __init__(self):
        self._models = {}

    def _build_model(self, provider: str, model_name: str):
        # Without an explicit timeout a stalled provider hangs the call forever,
        # and because batches run sequentially that stalls the ENTIRE batch --
        # no fallback, no escalation, no progress. A bounded wait turns a hang
        # into a normal provider failure that the fallback path already handles.
        if provider == "google":
            return ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=settings.GEMINI_API_KEY,
                timeout=LLM_TIMEOUT_SECONDS,
                max_retries=1,
            )
        if provider == "groq":
            return ChatGroq(
                model=model_name,
                groq_api_key=settings.GROQ_API_KEY,
                timeout=LLM_TIMEOUT_SECONDS,
                max_retries=1,
            )
        raise ValueError(f"Unknown provider: {provider}")

    def get_model(self, provider: str, model_name: str):
        key = f"{provider}:{model_name}"
        if key not in self._models:
            self._models[key] = self._build_model(provider, model_name)
        return self._models[key]

    async def call(
        self,
        role: str,
        system_prompt: str,
        human_prompt: str,
        response_model: Type[T],
    ) -> T:
        if role not in ROLE_MODEL_CONFIG:
            raise ValueError(f"Unknown role '{role}' -- no model configured. Add it to ROLE_MODEL_CONFIG.")
        cfg = ROLE_MODEL_CONFIG[role]

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]

        attempts = [
            (cfg["primary_provider"], cfg["primary_model"]),
            (cfg["fallback_provider"], cfg["fallback_model"]),
        ]

        last_error: Exception | None = None
        for attempt_num, (provider, model_name) in enumerate(attempts):
            is_fallback = attempt_num > 0
            try:
                model = self.get_model(provider, model_name)
                # include_raw=True returns {"raw": AIMessage, "parsed": Model,
                # "parsing_error": ...}. Needed because the parsed Pydantic model
                # alone carries NO usage metadata, which is why token counts
                # logged as 0 and left the budget cap unable to trip.
                structured_llm = model.with_structured_output(response_model, include_raw=True)

                start_time = datetime.now()
                envelope = await structured_llm.ainvoke(messages)
                latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                parsing_error = envelope.get("parsing_error")
                result = envelope.get("parsed")
                if parsing_error or result is None:
                    # Treat unparseable output as a provider failure so the
                    # fallback runs, instead of returning None downstream.
                    raise ValueError(f"Structured output parsing failed: {parsing_error}")

                # BUG FIX: estimated_cost_usd was never written, so
                # llm_usage_repo.get_monthly_spend() always summed to 0 and the
                # $5 monthly cap could never trip -- the budget guard was
                # decorative. Token counts come from the provider's own
                # response metadata; when a provider omits them we record 0
                # tokens rather than guessing, and the zero is visible in the
                # log rather than silently inflating a fake spend figure.
                input_tokens, output_tokens = _extract_token_usage(envelope.get("raw"))
                cost = estimate_cost_usd(provider, model_name, input_tokens, output_tokens)

                await llm_usage_repo.log_usage({
                    "role": role,
                    "provider": provider,
                    "model_id": model_name,
                    "latency_ms": latency_ms,
                    "was_fallback": is_fallback,
                    # Column names must match the llm_usage_log schema exactly
                    # (prompt_/completion_/total_tokens, not input_/output_).
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                    "estimated_cost_usd": cost,
                })
                if is_fallback:
                    logger.warning(f"'{role}' succeeded on fallback provider '{provider}' after primary failed.")
                return result
            except Exception as e:
                last_error = e
                logger.error(f"LLM call failed for role='{role}' provider='{provider}' model='{model_name}': {e}")

        raise RuntimeError(f"All providers failed for role '{role}'") from last_error


llm_provider = LLMProvider()
