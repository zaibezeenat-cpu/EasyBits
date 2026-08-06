"""
Deterministic SEO compliance guards applied to the Writer's output.

The Writer is an LLM: it will not reliably self-limit keyword repetition, so
keyword density is enforced here in code (the same philosophy that already makes
the product name and meta description deterministic) rather than by asking the
model and hoping. Keep the first few exact focus-keyword occurrences (Rank Math
needs >= 3) and replace the surplus with a natural short form so density stays
under the 2.5% stuffing ceiling regardless of what the model produced.
"""
import re

from app.models.writer_output import WriterOutput

MIN_KEYWORD_OCCURRENCES = 3
KEYWORD_DENSITY_MAX = 0.025


def count_keyword_occurrences(segments: list[str], keywords: list[str]) -> int:
    """
    Counts how many times ANY of `keywords` appears across `segments`, counting
    each stretch of text ONCE.

    WHY THIS IS NOT `sum(text.count(k) for k in keywords)`
    -----------------------------------------------------
    Our keyword sets overlap heavily by construction: the primary is
    "WestPoint Pakistan WF-6807", the secondary is "WF-6807 Hair Straightener",
    and the LSI keywords are phrases like "ceramic hair straightener". The words
    "hair straightener" sit inside four of the five, so per-keyword counting
    charges the same words several times over.

    Measured on the real WF-6807 copy: per-keyword counting reported 8
    occurrences where only 5 stretches of text exist -- a 60% overstatement.
    That inflation is not cosmetic: it feeds the density check, so genuinely
    clean copy is failed as keyword stuffing, the Writer is asked to fix a
    problem it does not have, and the product can burn all three attempts and
    land in Manual Review.

    Longest-first alternation is what makes the count non-overlapping: the regex
    engine prefers the longest branch at each position, so a match of
    "WestPoint Pakistan WF-6807" consumes those words and the shorter keywords
    inside it cannot match them again.
    """
    real = [k.strip() for k in keywords if k and k.strip()]
    if not real:
        return 0
    # Longest first -- alternation is first-match-wins, not longest-match-wins.
    pattern = re.compile(
        "|".join(re.escape(k) for k in sorted(set(real), key=len, reverse=True)),
        re.IGNORECASE,
    )
    return sum(len(pattern.findall(segment or "")) for segment in segments)


def enforce_keyword_density(
    writer_output: WriterOutput,
    focus_keyword: str,
    replacement: str,
    secondary_keyword: str = "",
    lsi_keywords: list[str] = None,
    max_density: float = KEYWORD_DENSITY_MAX,
    min_occurrences: int = MIN_KEYWORD_OCCURRENCES,
) -> WriterOutput:
    """Cap exact focus-keyword density across the Writer's body fields.

    Args:
        writer_output: The model's content (not mutated; a copy is returned).
        focus_keyword: The exact phrase Rank Math measures (the product name).
        replacement: A natural short form (e.g. the model number) for the surplus.
        max_density: Stuffing ceiling (occurrences / word count).
        min_occurrences: Rank Math's presence floor -- never drop below this.

    Returns:
        A copy of writer_output with surplus focus-keyword occurrences (beyond a
        comfortable in-range count) replaced by ``replacement``. The earliest
        occurrences are kept, so the high-value hero slot retains the keyword.
    """
    focus_keyword = (focus_keyword or "").strip()
    if not focus_keyword or not replacement:
        return writer_output

    wo = writer_output.model_copy(deep=True)
    pattern = re.compile(re.escape(focus_keyword), re.IGNORECASE)

    all_keywords = [focus_keyword.lower()]
    if secondary_keyword.strip():
        all_keywords.append(secondary_keyword.strip().lower())
    if lsi_keywords:
        for kw in lsi_keywords:
            if kw.strip():
                all_keywords.append(kw.strip().lower())
    all_keywords = list(set(all_keywords))

    segments = [
        wo.hero_heading, wo.hero_paragraph, *wo.feature_texts, *wo.features_bullets,
        *[f.answer for f in wo.faqs],
    ]
    word_count = sum(len(s.split()) for s in segments)
    ceiling = int(max_density * word_count)

    # Sort keywords by length descending so we don't accidentally replace a short
    # keyword inside a longer keyword first (e.g., replacing "WF-6807" inside
    # "WF-6807 Hair Straightener").
    all_keywords.sort(key=len, reverse=True)

    for kw in all_keywords:
        combined_occurrences = count_keyword_occurrences(segments, all_keywords)

        if combined_occurrences <= ceiling:
            break

        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        current_occ = sum(len(pattern.findall(s)) for s in [
            wo.hero_heading, wo.hero_paragraph, *wo.feature_texts, *wo.features_bullets, *[f.answer for f in wo.faqs]
        ])
        
        is_primary = (kw == focus_keyword.lower())
        floor = min_occurrences if is_primary else 1
        
        if current_occ <= floor:
            continue
            
        excess = combined_occurrences - int(0.02 * word_count)
        remove_count = min(excess, current_occ - floor)
        target_keep = current_occ - remove_count

        seen = 0
        def repl(match: re.Match) -> str:
            nonlocal seen
            seen += 1
            return match.group(0) if seen <= target_keep else replacement

        wo.hero_heading = pattern.sub(repl, wo.hero_heading)
        wo.hero_paragraph = pattern.sub(repl, wo.hero_paragraph)
        wo.feature_texts = [pattern.sub(repl, t) for t in wo.feature_texts]
        wo.features_bullets = [pattern.sub(repl, b) for b in wo.features_bullets]
        for faq in wo.faqs:
            faq.answer = pattern.sub(repl, faq.answer)

    return wo


def ensure_lsi_in_body(writer_output: WriterOutput, lsi_keywords: list[str]) -> WriterOutput:
    """Guarantee every LSI keyword appears in the body text.

    Rank Math wants each secondary (LSI) keyword present in the copy. The LLM
    generates them but does not always weave them all in, so any missing ones are
    added as one natural closing sentence to the hero paragraph. LSI keywords are
    real buyer search phrases, so surfacing them this way is honest and keeps the
    product out of a review loop it would otherwise never escape.
    """
    wo = writer_output.model_copy(deep=True)
    body = " ".join(
        [wo.hero_paragraph, *wo.feature_texts, *wo.features_bullets,
         *[f.answer for f in wo.faqs]]
    ).lower()

    missing = [kw.strip() for kw in lsi_keywords if kw.strip() and kw.strip().lower() not in body]
    if not missing:
        return wo

    para = wo.hero_paragraph.rstrip()
    if para and not para.endswith((".", "!", "?")):
        para += "."
    wo.hero_paragraph = f"{para} Shoppers also look for it as {', '.join(missing)}.".strip()
    return wo
