"""
Warranty cross-check.

The warranty comes from the operator's input sheet, which makes it a hand-typed
value on a career-critical field: publishing "10 years" when the real cover is
1 year is a claim the business has to honour. This compares the typed warranty
against what the scraped sources actually say and flags disagreement for a human
instead of silently trusting either side.

Deliberately NOT auto-correcting. Sources are retailer pages that are themselves
sometimes wrong or refer to a different variant, so overwriting the operator's
value would trade one unverified number for another. A conflict is surfaced; a
person decides.
"""
import re

from pydantic import BaseModel

# "10 years", "5 year", "10-yr", "24 months"
_DURATION_PATTERN = re.compile(
    r"(\d+)\s*[-\s]?\s*(years?|yrs?|months?|mos?)\b",
    re.IGNORECASE,
)


class WarrantyCheck(BaseModel):
    """Outcome of comparing the operator's warranty against scraped content."""
    input_durations: list[str] = []
    source_durations: list[str] = []
    agrees: bool = True
    checked: bool = False          # False when the sources say nothing about warranty
    detail: str = ""


def _normalise_unit(unit: str) -> str:
    unit = unit.lower().rstrip("s")
    if unit in {"yr", "year"}:
        return "year"
    if unit in {"mo", "month"}:
        return "month"
    return unit


def extract_durations(text: str) -> list[str]:
    """
    Pulls warranty durations as normalised "<n> <unit>" strings.

    Months are converted to years when they divide evenly so "24 months" and
    "2 years" are recognised as the same cover rather than a false conflict.
    """
    if not text:
        return []

    found: list[str] = []
    for amount, unit in _DURATION_PATTERN.findall(text):
        value, normalised = int(amount), _normalise_unit(unit)
        if normalised == "month" and value % 12 == 0:
            value, normalised = value // 12, "year"
        token = f"{value} {normalised}"
        if token not in found:
            found.append(token)
    return found


# Generic component buckets -- brand-agnostic on purpose. Haier publishes a
# three-tier warranty (compressor / electronics / other parts), but the owner
# was explicit that not every brand does, so nothing here is Haier-specific.
#
# ORDER MATTERS: most-specific first, "parts" last. A clause is assigned to the
# FIRST bucket it matches and NO OTHER. This is not cosmetic -- Haier's own
# electronics tier is literally worded "Electronics part (VFD, PCB, ...): 3
# Year", which contains the word "part". Without the specific-first rule, that
# 3-year electronics tier also lands in the generic "parts" bucket and then
# collides with the real "Other part: 1 Year" tier, inventing a contradiction
# that is not there. The Haier pilot produced exactly that false positive.
_COMPONENT_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("compressor", ("compressor",)),
    ("motor", ("motor",)),
    ("electronics", ("electronic", "pcb", "vfd", "thermostat", "display", "led", "circuit", "board")),
    ("parts", ("part", "other")),
)

# Split a warranty phrase into the clauses that each pair a component with a
# duration: "10 Year Compressor; 3 Year Electronics * 1 Year Other Parts".
_CLAUSE_SPLIT = re.compile(r"[;*•\n|]+|(?:\s-\s)")


def _component_durations(text: str) -> dict[str, set[str]]:
    """
    Maps each component bucket to the durations stated for it in `text`.

    Works clause by clause so a duration is tied to the component named in the
    same clause, which is what lets a real contradiction (same component, a
    different number) be told apart from a source that simply lists fewer tiers.
    Each clause counts toward only its most-specific bucket (see the ordering
    note above).
    """
    result: dict[str, set[str]] = {}
    for clause in _CLAUSE_SPLIT.split(text or ""):
        durations = set(extract_durations(clause))
        if not durations:
            continue
        lowered = clause.lower()
        for bucket, keywords in _COMPONENT_BUCKETS:
            if any(k in lowered for k in keywords):
                result.setdefault(bucket, set()).update(durations)
                break  # most-specific bucket only -- do not also fill "parts"
    return result


def verify_warranty(input_warranty: str, source_content: str) -> WarrantyCheck:
    """
    Cross-checks the operator's warranty against scraped source text.

    POLICY (owner decision, 2026-07-22): the operator's warranty is
    AUTHORITATIVE. It is typed from the brand's own warranty card, which is more
    reliable than a retailer listing, so a tier the sources simply do not mention
    is NOT a conflict -- it is accepted. The check escalates ONLY on a direct
    contradiction: the SAME component carrying a DIFFERENT duration in the
    sources (e.g. sheet says a 10-year compressor, a source says 5-year). This
    replaced an earlier rule that required every tier to appear in the sources,
    which wrongly escalated a correct Haier warranty because retailers listed
    only the headline cover.

    `checked=False` still means the sources say nothing to compare against.
    """
    input_durations = extract_durations(input_warranty)
    source_durations = extract_durations(source_content)

    if not input_durations:
        return WarrantyCheck(
            checked=False,
            detail="No duration found in the supplied warranty text; nothing to verify.",
        )

    if not source_durations:
        return WarrantyCheck(
            input_durations=input_durations,
            checked=False,
            detail=(
                f"Sources do not state a warranty, so {input_durations} could not be "
                f"cross-checked. Using the supplied value as-is."
            ),
        )

    # A contradiction is a component the operator AND the sources both describe,
    # with no duration in common -- i.e. the sources give a different number for
    # the same part, not merely a shorter list of parts.
    input_components = _component_durations(input_warranty)
    source_components = _component_durations(source_content)

    contradictions: list[str] = []
    for bucket, in_durations in input_components.items():
        src = source_components.get(bucket)
        if src and in_durations.isdisjoint(src):
            contradictions.append(
                f"{bucket}: you have {sorted(in_durations)} but a source states {sorted(src)}"
            )

    if contradictions:
        return WarrantyCheck(
            input_durations=input_durations,
            source_durations=source_durations,
            agrees=False,
            checked=True,
            detail=(
                "WARRANTY CONTRADICTION on the same component -- "
                + "; ".join(contradictions)
                + ". Verify against the brand's official warranty before publishing."
            ),
        )

    # No component-level disagreement. Accept the operator's warranty; note when
    # the sources merely confirmed part of it.
    confirmed = [d for d in input_durations if d in source_durations]
    return WarrantyCheck(
        input_durations=input_durations,
        source_durations=source_durations,
        agrees=True,
        checked=True,
        detail=(
            f"Supplied warranty {input_durations} accepted (operator-authoritative). "
            f"Sources corroborated {confirmed or 'none of the tiers'} and contradicted none."
        ),
    )


def build_source_text(scraped_data: list[dict]) -> str:
    """Concatenates scraped source content for cross-checking."""
    return "\n".join(doc.get("content", "") for doc in (scraped_data or []))


def warranty_conflict_detail(check: WarrantyCheck) -> str | None:
    """Returns an escalation reason when the check found a real disagreement."""
    if check.checked and not check.agrees:
        return check.detail
    return None
