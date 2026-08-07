"""
Cross-source corroboration: turn several sources' claims about one field into a
single resolved value plus a confidence level.

THE IDEA (owner's request, 2026-07-22)
--------------------------------------
"Compare the values across every source and take the value the sources agree on."
Accuracy comes from CONSENSUS, not from trusting one fragile page. The more
independent sources agree on a value, the more certain it is.

This also fixes a latent bug: `ExtractionResult.confirmed_value()` used to return
a value only when EXACTLY ONE confirmed citation existed, so two sources stating
the same value cancelled out and the field was treated as missing. Here,
agreement CONFIRMS.

Deliberately independent of `ExtractionResult` (it accepts any objects exposing
`field_name`, `value`, `source_url`, `source_type`, `confidence`) so the model
can import this without a cycle.

Trust order, and what counts as confirmed:
  * an OFFICIAL brand source stating a value            -> confirmed (authoritative)
  * >= 2 INDEPENDENT non-official domains agreeing       -> corroborated (confirmed)
  * exactly one non-official domain                      -> single_source (weak)
  * two indistinguishable groups disagreeing             -> conflict (escalate)
A single unverified web page is never enough on its own; that is the whole point.
"""
import re
from typing import Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel

ResolutionStatus = Literal["confirmed", "corroborated", "single_source", "conflict", "unknown"]

# Source tiers, most authoritative first. Mirrors the discovery tiers.
_TIER_RANK = {"official": 3, "trusted_secondary": 2, "web": 1, "user_estimate": 0}

_UNKNOWN = "UNKNOWN"


class _CitationLike(Protocol):
    field_name: str
    value: str
    source_url: str | None
    source_type: str
    confidence: str


class FieldResolution(BaseModel):
    field_name: str
    value: str | None           # chosen ORIGINAL wording; None when unknown/conflict
    status: ResolutionStatus
    supporting_domains: list[str] = []
    conflicting_values: list[str] = []   # populated only when status == "conflict"

    @property
    def is_confirmed(self) -> bool:
        """A value safe to use downstream: an official source or real corroboration."""
        return self.status in ("confirmed", "corroborated")


# --- Value normalisation ----------------------------------------------------

# Longer phrases first so "cubic feet" is folded before a stray "ft".
_UNIT_REPLACEMENTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bcubic\s*feet\b|\bcu\.?\s*ft\.?\b|\bcuft\b", re.IGNORECASE), "cuft"),
    (re.compile(r"\blit(?:re|er)s?\b", re.IGNORECASE), "l"),
    (re.compile(r"\bkilograms?\b|\bkgs?\b", re.IGNORECASE), "kg"),
    (re.compile(r"\btons?\b", re.IGNORECASE), "ton"),
    (re.compile(r"\bwatts?\b", re.IGNORECASE), "w"),
    (re.compile(r"\binch(?:es)?\b", re.IGNORECASE), "in"),
)

_DECIMAL = re.compile(r"\d+\.\d+")


def _strip_trailing_zero(match: re.Match) -> str:
    """'1.0' -> '1', '1.50' -> '1.5' (reuses name_builder's rule for consistency)."""
    trimmed = match.group(0).rstrip("0").rstrip(".")
    return trimmed or "0"


# 1 cubic foot = 28.3168 litres. Refrigerator capacity is quoted both ways
# across Pakistani sellers ("12 Cu Ft" vs "340 Liters"), so they must fold to
# the SAME token or two sellers describing the identical fridge look like a
# conflict. Brands market rounded cubic feet, so litres are converted and
# rounded to the nearest whole cubic foot to match how they are advertised.
_LITRES_PER_CUFT = 28.3168
_LITRES_TOKEN = re.compile(r"^(\d+(?:\.\d+)?)\s*l$")


def _fold_volume_units(text: str) -> str:
    """Convert a bare litres capacity to canonical rounded cubic feet."""
    m = _LITRES_TOKEN.match(text)
    if m:
        litres = float(m.group(1))
        cuft = round(litres / _LITRES_PER_CUFT)
        return f"{cuft} cuft"
    return text


def normalize_value(value: str) -> str:
    """
    Folds trivially-different wordings of the same fact to one canonical form, so
    consensus counting is not defeated by punctuation, unit spelling, OR the unit
    system used:

        "9 Cu Ft" / "9 cubic feet" / "9 cu. ft."  -> "9 cuft"
        "255 Liters" / "255 L"                     -> "9 cuft"   (converted + rounded)
        "246 Liters"                               -> "9 cuft"
        "1.0 Ton"                                  -> "1 ton"
    """
    text = (value or "").strip().lower()
    for pattern, replacement in _UNIT_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    text = _DECIMAL.sub(_strip_trailing_zero, text)
    # Drop punctuation, collapse whitespace.
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Cross-unit fold: litres -> rounded cubic feet, so "340 l" == "12 cuft".
    return _fold_volume_units(text)


def _domain(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url if "//" in url else f"//{url}").netloc.lower()
    return host.removeprefix("www.")


class _Group:
    def __init__(self, normalized: str):
        self.normalized = normalized
        self.original_values: list[str] = []
        self.domains: set[str] = set()
        self.tiers: set[int] = set()
        self.has_official = False

    @property
    def independent_domains(self) -> int:
        return len(self.domains)

    @property
    def strength(self) -> int:
        # 3 = confirmed (official), 2 = corroborated (>=2 domains), 1 = single.
        if self.has_official:
            return 3
        if self.independent_domains >= 2:
            return 2
        return 1

    @property
    def best_tier(self) -> int:
        return max(self.tiers) if self.tiers else 0

    def representative(self) -> str:
        """The wording to surface: the most frequently stated original value."""
        return max(set(self.original_values), key=self.original_values.count)


def resolve_field(field_name: str, citations: list[_CitationLike]) -> FieldResolution:
    """Resolves one field's value from all citations that mention it."""
    relevant = [
        c for c in citations
        if c.field_name == field_name
        and c.confidence == "confirmed"
        and (c.value or "").strip().upper() != _UNKNOWN
    ]
    if not relevant:
        return FieldResolution(field_name=field_name, value=None, status="unknown")

    groups: dict[str, _Group] = {}
    for c in relevant:
        key = normalize_value(c.value)
        if not key:
            continue
        group = groups.setdefault(key, _Group(key))
        group.original_values.append(c.value)
        dom = _domain(c.source_url)
        if dom:
            group.domains.add(dom)
        else:
            # A confirmed citation with no URL still counts as one anonymous
            # source, so agreement is not silently dropped.
            group.domains.add(f"_anon_{c.source_type}_{len(group.domains)}")
        group.tiers.add(_TIER_RANK.get(c.source_type, 0))
        if c.source_type == "official":
            group.has_official = True

    if not groups:
        return FieldResolution(field_name=field_name, value=None, status="unknown")

    ranked = sorted(
        groups.values(),
        key=lambda g: (g.strength, g.independent_domains, g.best_tier),
        reverse=True,
    )
    winner = ranked[0]

    # Conflict only when a rival is genuinely indistinguishable from the winner:
    # same strength AND same independent-domain count, different value. If the
    # winner is separable by either measure, the tie-break already chose it.
    for rival in ranked[1:]:
        if (rival.strength == winner.strength
                and rival.independent_domains == winner.independent_domains):
            return FieldResolution(
                field_name=field_name,
                value=None,
                status="conflict",
                conflicting_values=sorted({g.representative() for g in ranked}),
            )
        break  # only the closest rival can tie; the rest rank strictly lower

    status: ResolutionStatus = (
        "confirmed" if winner.strength == 3
        else "corroborated" if winner.strength == 2
        else "single_source"
    )
    return FieldResolution(
        field_name=field_name,
        value=winner.representative(),
        status=status,
        supporting_domains=sorted(d for d in winner.domains if not d.startswith("_anon_")),
    )


def resolve_all(field_names: list[str], citations: list[_CitationLike]) -> dict[str, FieldResolution]:
    return {name: resolve_field(name, citations) for name in field_names}
