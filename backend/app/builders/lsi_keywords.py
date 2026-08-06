"""
Keeps the LSI (secondary) keywords tied to the actual product.

THE PROBLEM THIS SOLVES (operator report, 2026-08-06)
-----------------------------------------------------
The Writer was asked for "real search phrases a buyer would type" and returned
phrases that describe the CATEGORY rather than the product. Two consecutive real
runs of the same hair straightener produced:

    run 1:  ceramic hair straightener | hair straightener for frizzy hair
            | lightweight hair straightener
    run 2:  hair straightening at home | ceramic hair straighteners
            | beauty tools for hair

"beauty tools for hair" and "hair straightening at home" say nothing about
WF-6807. They would rank the page for traffic that bounces, and they push the
brand and model -- the terms a buyer with purchase intent actually types -- out
of the five keyword slots Rank Math scores.

Worse, some of them are unverified CLAIMS. "lightweight hair straightener"
asserts something no source confirmed. The rest of this pipeline refuses to
publish an unconfirmed capacity or wattage; an unconfirmed adjective in a
keyword is the same fabrication wearing a different hat.

THE RULE
--------
A keyword may stay only if it is anchored to something we KNOW: the brand, the
model number, or a spec value a source actually confirmed. Anything else is
dropped and replaced with a deterministic phrase built from those same
confirmed facts -- so the slots are always full, and always true.

This mirrors how the product name, meta description and SEO title are already
handled: the LLM supplies the angle, code decides what is allowed to ship.
"""
import re

# A confirmed spec value can be a long phrase ("Ceramic Coating Plate",
# "220-240V - 50Hz"). Searchers type the distinctive word, not the whole cell,
# so values are matched token by token. Tokens this short or this generic carry
# no product identity and would let anything through.
_MIN_ANCHOR_TOKEN = 4
_GENERIC_TOKENS = frozenset({
    "with", "and", "the", "for", "type", "size", "unit", "watt", "watts",
    "volt", "volts", "plate", "plates", "power", "switch", "cord", "light",
    "control", "element", "system", "model", "number", "feature", "features",
    "available", "included", "colour", "color", "black", "white", "silver",
})


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t}


# A measurement is the most distinctive thing a spec can carry -- "1.5 Ton",
# "35 Watts", "9 Cu Ft" -- and it is exactly what buyers type ("1.5 ton inverter
# AC"). Token matching alone cannot see it: the number is too short to clear the
# word floor and the unit on its own ("ton", "watts") is far too generic to
# anchor anything. So measurements are matched as the NUMBER AND UNIT TOGETHER,
# which is both specific and safe -- "top 5 straighteners" shares the 5 but not
# the pair.
_MEASUREMENT = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)", re.IGNORECASE)


def _measurements(text: str) -> set[str]:
    """Normalised "<number> <unit>" pairs found in a value or a keyword."""
    return {
        f"{num} {unit.lower()}"
        for num, unit in _MEASUREMENT.findall((text or "").lower())
    }


def _anchor_tokens(brand: str, model: str, product_type: str,
                   facts: dict[str, str | None]) -> set[str]:
    """
    Every token that proves a phrase is about THIS product: the brand, the model
    number, and the tokens of each confirmed spec value.

    THE PRODUCT TYPE IS DELIBERATELY EXCLUDED, and this is the whole subtlety.
    The type ("Hair Straightener") is itself a confirmed fact, so counting it as
    an anchor lets EVERY category phrase through -- "beauty tools for hair" and
    "hair straightening at home" both contain "hair", and the filter passes
    exactly the keywords it exists to remove. An anchor has to distinguish this
    unit from its siblings, and the category noun is what it shares WITH them.

    Only CONFIRMED values are included -- `facts` comes from
    ExtractionResult.confirmed_value(), which already returns None for anything
    resting on a single unverified source. So a keyword can never be anchored to
    a fact the pipeline itself refused to publish.
    """
    type_tokens = _tokens(product_type)

    anchors: set[str] = set()
    anchors |= {t for t in _tokens(brand) if len(t) >= _MIN_ANCHOR_TOKEN}
    # Model numbers are the strongest anchor and are often short ("WF-6807" ->
    # {"wf", "6807"}), so they bypass the length floor.
    anchors |= _tokens(model)

    for value in (facts or {}).values():
        if not value or str(value).strip().upper() == "UNKNOWN":
            continue
        for token in _tokens(str(value)):
            if len(token) >= _MIN_ANCHOR_TOKEN and token not in _GENERIC_TOKENS:
                anchors.add(token)

    return {a for a in anchors - type_tokens if a}


def is_product_specific(keyword: str, brand: str, model: str, product_type: str,
                        facts: dict[str, str | None]) -> bool:
    """
    True when `keyword` names the brand, the model, or a confirmed spec value --
    something that sets this unit apart from others of the same type.

        "ceramic hair straightener"      -> True
            ("ceramic" comes from the confirmed "Ceramic Coating Plate")
        "WF-6807 price in Pakistan"      -> True  (names the model)
        "beauty tools for hair"          -> False (category, not product)
        "hair straightening at home"     -> False (category, not product)
        "lightweight hair straightener"  -> False
            (nothing confirmed "lightweight" -- an unverified claim)
    """
    if not keyword or not keyword.strip():
        return False
    if _tokens(keyword) & _anchor_tokens(brand, model, product_type, facts):
        return True
    # A measurement quoted from a confirmed spec anchors just as well as a word.
    confirmed_measurements: set[str] = set()
    for value in (facts or {}).values():
        if value and str(value).strip().upper() != "UNKNOWN":
            confirmed_measurements |= _measurements(str(value))
    return bool(_measurements(keyword) & confirmed_measurements)


def _deterministic_candidates(brand: str, model: str, product_type: str,
                              facts: dict[str, str | None]) -> list[str]:
    """
    Replacement keywords built only from things a source confirmed.

    Ordered by how a buyer actually searches: brand + type first (broad but
    correct), then the model with purchase intent, then the distinctive spec
    that separates this unit from its siblings.
    """
    brand = (brand or "").strip()
    model = (model or "").strip()
    ptype = (product_type or "").strip()

    candidates: list[str] = []
    if brand and ptype:
        candidates.append(f"{brand} {ptype}")
    if model:
        # The highest-intent query pattern in this market, and factual.
        candidates.append(f"{model} price in Pakistan")

    # A confirmed spec makes the most specific phrase of all -- "ceramic plate
    # hair straightener" is both true and something people search for.
    for value in (facts or {}).values():
        if not value or str(value).strip().upper() == "UNKNOWN" or not ptype:
            continue
        for token in _tokens(str(value)):
            if len(token) >= _MIN_ANCHOR_TOKEN and token not in _GENERIC_TOKENS:
                candidates.append(f"{token} {ptype}")
                break  # one phrase per spec, the first distinctive token

    if brand and model:
        candidates.append(f"{brand} {model}")

    return candidates


def repair_lsi_keywords(
    proposed: list[str],
    *,
    brand: str,
    model: str,
    product_type: str,
    facts: dict[str, str | None],
    minimum: int = 2,
    maximum: int = 3,
) -> tuple[list[str], list[str]]:
    """
    Filters the Writer's LSI keywords down to the ones anchored in fact and tops
    the list back up deterministically.

    Returns (kept_keywords, rejected_keywords) -- the rejected list is returned
    rather than discarded so the caller can log WHICH phrases the model drifted
    to. Without that, this silently papers over a prompt that is going wrong.

    Never returns fewer than `minimum` entries unless there is genuinely nothing
    to build from (no brand, no model, no product type, no confirmed facts), in
    which case the Writer's originals are handed back untouched: shipping
    slightly loose keywords beats shipping none and failing the schema.
    """
    kept: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for keyword in proposed or []:
        cleaned = " ".join((keyword or "").split())
        if not cleaned or cleaned.lower() in seen:
            continue
        if is_product_specific(cleaned, brand, model, product_type, facts):
            kept.append(cleaned)
            seen.add(cleaned.lower())
        else:
            rejected.append(cleaned)

    for candidate in _deterministic_candidates(brand, model, product_type, facts):
        if len(kept) >= max(minimum, min(len(proposed or []), maximum)):
            break
        cleaned = " ".join(candidate.split())
        if cleaned.lower() in seen:
            continue
        kept.append(cleaned)
        seen.add(cleaned.lower())

    if len(kept) < minimum:
        # Nothing verifiable to build from. Keep the originals rather than emit
        # an invalid WriterOutput -- the schema requires at least `minimum`.
        return list(proposed or [])[:maximum], rejected

    return kept[:maximum], rejected
