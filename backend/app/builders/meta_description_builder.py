"""
Deterministic meta-description assembly.

WHY THIS IS NOT LEFT TO THE LLM
-------------------------------
Rank Math's meta-description test is a hard CHARACTER-count window, and LLMs
cannot count characters reliably -- the Haier pilot produced 185 characters when
the prompt asked for 150-160. Character budgets are exactly the kind of
constraint a program enforces perfectly and a model does not, so the meta is
built here from parts instead of being trusted to the writer.

The four locked requirements (phase1.md §6.8) are all deterministic anchors:
  1. begins with the exact focus keyword,
  2. mentions every warranty duration NUMBER,
  3. ends with the exact per-category CTA sentence,
  4. total length inside the window.
Only a short connective phrase is creative, and the writer supplies just that.
"""
import re

from app.builders.warranty_verifier import extract_durations

# phase1.md §6.8 line 147 locks 151-155; the validator allows 150-160. Targeting
# 151-155 satisfies both with no edge effects.
MIN_LEN = 151
MAX_LEN = 155


def _abbreviate_durations(warranty_phrase: str) -> str:
    """'10 Year ...; 3 Year ...' -> '10-yr, 3-yr' (compact, numbers preserved)."""
    seen: list[str] = []
    for dur in extract_durations(warranty_phrase):
        # extract_durations yields e.g. "10 year" / "6 month"
        n, unit = dur.split()
        abbr = f"{n}-{'yr' if unit.startswith('year') else 'mo'}"
        if abbr not in seen:
            seen.append(abbr)
    return ", ".join(seen)


def build_meta_description(
    focus_keyword: str,
    warranty_phrase: str,
    cta: str,
    selling_phrase: str = "",
) -> str:
    """
    Assembles a 151-155 char meta description that always satisfies the four
    locked checks. `selling_phrase` is the writer's short creative middle; it is
    trimmed or padded to make the whole string land in the window, so the writer
    never has to count characters.

    Raises ValueError only when the fixed anchors (a very long focus keyword plus
    the CTA) already exceed the window on their own -- an unbuildable case the
    caller escalates rather than shipping a malformed meta.
    """
    head = focus_keyword.strip().rstrip(".")
    tail = cta.strip()
    warranty_bit = _abbreviate_durations(warranty_phrase)
    warranty_segment = f" Warranty: {warranty_bit}." if warranty_bit else ""

    # The no-middle form; the middle text fills the remaining budget precisely.
    fixed = f"{head}.{warranty_segment} {tail}"
    if len(fixed) > MAX_LEN:
        raise ValueError(
            f"Focus keyword + warranty + CTA is already {len(fixed)} chars, over the "
            f"{MAX_LEN} limit, before any description text. The product name is too long "
            f"to fit a compliant meta description; escalate for a manual meta."
        )

    # Character budget for the middle so the WHOLE string lands in [MIN, MAX].
    # Overhead is everything except the middle in "{head}. {middle}.{warr} {tail}".
    overhead = len(head) + 2 + 1 + len(warranty_segment) + 1 + len(tail)
    lo, hi = MIN_LEN - overhead, MAX_LEN - overhead

    if hi < 1:
        # No room for a middle without overshooting; the no-middle form is the
        # best fit and already <= MAX (checked above).
        return fixed

    # When a long product name leaves almost no room, the writer's phrase can
    # only be trimmed to a broken fragment ("This."). Below a usable width, use
    # neutral filler instead so the sentence still reads as a whole word.
    phrase = selling_phrase if hi >= 15 else ""
    middle = _size_middle(phrase, lo, hi)
    return f"{head}. {middle}.{warranty_segment} {tail}"


# Neutral, factual filler used only to reach the length floor -- never a product
# claim, so it cannot introduce an unverified specification.
_FILLER = (
    " Genuine brand unit built for reliable everyday performance and efficient "
    "low power operation in any home across Pakistan"
)


def _size_middle(selling_phrase: str, lo: int, hi: int) -> str:
    """
    Produces middle text whose length is in [max(lo,1), hi], padding a short
    phrase with neutral filler and trimming an over-long one at a word boundary
    where possible (a mid-word cut only as a last resort to honour the ceiling).
    """
    lo = max(lo, 1)
    raw = re.sub(r"\s+", " ", (selling_phrase or "")).strip().rstrip(".")
    if len(raw) < hi:
        raw = (raw + _FILLER).strip()
    if len(raw) <= hi:
        return raw

    cut = raw[:hi]
    space = cut.rfind(" ")
    if space >= lo:
        return cut[:space].rstrip()
    return cut.rstrip()
