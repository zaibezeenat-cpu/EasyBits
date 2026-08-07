"""
Structural checks on the Extractor system prompt.

WHY A PROMPT NEEDS TESTS
------------------------
The previous version instructed the model twice, contradictorily. An
`<inference_boundaries>` block said "you ARE PERMITTED to logically deduce
categorical specs", and Hard Rule 2 immediately below said "if a field is NOT
explicitly stated in ANY source document, you MUST output UNKNOWN". A model given
both follows whichever it weighs higher on the day, which is precisely the
inconsistency the operator saw across two runs of the same product.

Nothing caught it, because prompts are strings and strings are not tested. These
assertions run offline with no LLM calls, so they are free and CI-safe, and they
fail the moment the prompt regrows a contradiction or loses a placeholder.

They check STRUCTURE, not model behaviour. Behaviour is measured by running the
real extractor against real sources.
"""
import re

import pytest

from app.agents.extractor import EXTRACTOR_SYSTEM_PROMPT as PROMPT


# --- placeholders -----------------------------------------------------------

@pytest.mark.parametrize("placeholder", [
    "{category_name}",
    "{required_fields_json}",
    "{inferable_fields_json}",
    "{source_documents}",
])
def test_every_placeholder_the_caller_fills_is_present(placeholder):
    assert placeholder in PROMPT


def test_no_unfilled_placeholder_would_survive_formatting():
    """
    `safe_format` replaces only the keys it is handed; anything else ships to the
    model as a literal `{like_this}`. A placeholder added to the prompt but not to
    the call site is invisible until it confuses the model in production.
    """
    from app.graph import nodes  # imported lazily: pulls in the whole graph

    filled = nodes.safe_format(
        PROMPT,
        category_name="Vacuum Cleaner",
        required_fields_json='["vacuum_type"]',
        inferable_fields_json='["vacuum_type"]',
        source_documents="…",
    )
    # `<!-- ... -->` blocks illustrate the shape of a rendered source document
    # ("### SOURCE [{source_type}] {source_url}"). Those braces are deliberate
    # documentation, not slots to fill, so they are excluded before checking.
    without_comments = re.sub(r"<!--.*?-->", "", filled, flags=re.DOTALL)

    leftovers = re.findall(r"\{[a-z_]+\}", without_comments)
    assert not leftovers, f"unfilled placeholder(s) reach the model: {leftovers}"


# --- the contradiction that shipped -----------------------------------------

def test_the_prompt_does_not_contradict_itself_about_inference():
    """
    REGRESSION. Blanket permission to deduce cannot coexist with a blanket
    requirement to output UNKNOWN when nothing states the value.
    """
    blanket_permission = "You ARE PERMITTED to logically deduce" in PROMPT
    blanket_prohibition = (
        "If a field is NOT explicitly stated in ANY source document, you MUST output" in PROMPT
    )
    assert not (blanket_permission and blanket_prohibition), (
        "the prompt gives the model two opposing instructions about inference"
    )


def test_inference_is_scoped_to_a_named_list_not_to_a_category_of_field():
    """
    "categorical specs" is a judgement the model makes; a list of field keys is
    not. Scoping by list is what lets code enforce the same boundary.
    """
    assert "INFERABLE FIELDS" in PROMPT
    assert "{inferable_fields_json}" in PROMPT


def test_reading_is_presented_before_inferring():
    """
    Most 'missing' fields are stated in prose and were simply never looked for.
    Reading must come first so inference stays the exception.
    """
    assert PROMPT.index("READING") < PROMPT.index("INFERRING")


# --- the guardrails the prompt must keep --------------------------------

def test_prose_counts_as_a_statement():
    """The original failure: the model only searched specification tables."""
    lowered = PROMPT.lower()
    assert "does not have to sit in a specification table" in lowered or "prose counts" in lowered


def test_an_inference_is_required_to_carry_its_evidence():
    assert "exact_quote" in PROMPT


def test_measurements_are_declared_never_inferable():
    lowered = PROMPT.lower()
    assert "measurements are never inferable" in lowered


def test_a_negative_example_teaches_when_to_refuse():
    """
    Few-shot with only positive examples teaches the model to always produce an
    answer. The 'evidence fits two answers -> UNKNOWN' case has to be shown.
    """
    assert "When NOT to infer" in PROMPT


def test_the_empty_list_case_is_spelled_out():
    """Most categories will have no inferable fields; that must read as a full stop."""
    assert "If that list is empty" in PROMPT


def test_corroboration_instruction_is_intact():
    """
    The single most important rule in this prompt -- cite every source separately,
    even when they agree -- must not be lost while editing around it.
    """
    assert "Output a SEPARATE citation for EVERY source" in PROMPT
