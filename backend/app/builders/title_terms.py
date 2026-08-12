"""
Harvests series and feature terms from how other sellers title the same model.

The goal is a product title that uses the naming customers actually search for
("Luxury Ultra", "Titan", "Inverter Split") instead of only the bare spec
fields. The hard constraint is accuracy: a term that reaches the title is a
public claim about the product, so this module is built to REJECT terms far
more readily than to accept them.

Two independent gates before a term can be used:

  1. CORROBORATION -- the term must appear in titles from at least two distinct
     sources. A single seller's marketing adjective ("Super Deluxe Best Price")
     is not evidence about the hardware; two independent sellers using the same
     term is.

  2. NO CONTRADICTION -- the term must not conflict with a confirmed extracted
     fact. If extraction confirms the compressor is non-inverter, "Inverter"
     cannot enter the title no matter how many sellers use it.

Anything that fails either gate is dropped silently. A shorter title is always
preferable to a title asserting something unverified.
"""
import re
from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel

# Marketing filler that describes the listing, not the product. These never
# belong in a product title even when every competitor uses them.
_STOPWORDS = {
    "best", "price", "in", "pakistan", "buy", "online", "sale", "new", "latest",
    "original", "official", "genuine", "free", "delivery", "shipping", "offer",
    "discount", "cheap", "lowest", "model", "series", "with", "and", "for",
    "the", "a", "an", "of", "brand", "warranty", "years", "year", "installation",
    "store", "shop", "product", "products", "rs", "pkr", "karachi", "lahore",
    "islamabad", "wholesale", "retail", "imported", "stock", "available",
}

# NOTE: there is deliberately NO list of known feature terms here.
#
# An earlier version hardcoded AC vocabulary ("inverter", "heat & cool", "t3",
# "frost free"...). The catalogue spans 26 categories -- juicers, dispensers,
# ovens, fans, televisions, blenders -- so such a list is guaranteed to be
# incomplete and would silently fail to verify terms for every category it did
# not anticipate, exactly the way an invented "Inverter" category once broke
# every inverter AC.
#
# The rule below is category-agnostic instead: a term may enter a product title
# only if its words actually appear in the facts extraction confirmed for THIS
# product, whatever category it belongs to. That needs no vocabulary, scales to
# any new category automatically, and is strictly safer -- an unrecognised term
# is rejected rather than waved through.


# How many NOT-fact-backed (marketing) words may reach one title.
#
# Counted in WORDS, not phrases (corrected 2026-08-11 after review): harvesting
# emits phrases of up to four words, so a phrase cap of 2 let
# "Deluxe Heavy Duty Powerful" through as a single term -- four unverifiable
# marketing words in the title, which is precisely what the owner asked to
# prevent. What matters is words reaching the title, not how they were grouped.
#
# 2026-08-11, owner-directed: "if add it should add relevant perfect like I
# add, or just skip, because wrong combination makes title worse for SEO."
# A marketing word is verified on a trusted source's say-so alone, with no
# spec to check it against, so without a cap a single padded retailer title
# ("Deluxe Heavy Duty Powerful Turbo ...") would stuff every one of them
# into the product title. Three words covers what the owner's own reference
# titles use ("Deluxe" = 1, "2 in 1" = 3 but fact-backed so it does not count
# here), and it leaves the character budget for the fact-backed spec words
# that actually describe the product.
MAX_MARKETING_WORDS = 3


class TitleTerm(BaseModel):
    term: str
    frequency: int
    corroborated: bool
    verified: bool
    reason: str = ""
    # 2026-08-09, widened 2026-08-10 (owner-directed): a term from a TRUSTED
    # source -- official OR trusted_secondary -- is trusted on its own -- it
    # does not need a second unrelated seller repeating it, and it does not
    # need to match a confirmed SPEC fact, because a marketing/series word
    # ("Deluxe", "Handy") was never going to be a spec fact in the first
    # place. Originally official-only; widened after the owner reported real
    # marketing words missing from titles built from the SAME 1 official + 1
    # trusted_secondary source already being scraped for facts (no new
    # scraping added -- see harvest_title_terms's docstring). This mirrors
    # both ExtractionResult.confirmed_value's rule (official is already the
    # most authoritative tier, fact_corroboration._TIER_RANK) and
    # orchestrator.py's _brand_identity_ok (official+trusted_secondary get a
    # specific bounded trust allowance; unvetted `web` does not).
    from_trusted_source: bool = False
    # Set by verify_terms: True when the term is backed by this product's own
    # CONFIRMED SPEC FACTS (or its extracted series name), False when it was
    # verified only because a trusted source's title used the wording.
    #
    # The distinction exists because the two carry very different risk. A
    # fact-backed term ("DC Inverter", "Heat & Cool") is a real, verified
    # property -- any number of them can safely go in a title. A
    # marketing-only term ("Deluxe", "Heavy Duty") is trusted on the source's
    # say-so alone, so a single padded retailer title could otherwise stuff
    # a dozen of them into the title. select_title_features caps the latter.
    fact_backed: bool = False
    # Harvested from the product's OWN confirmed spec text rather than from
    # any seller's title. Recorded at harvest time so verify_terms does not
    # have to re-derive it by string-matching the canonical form back against
    # the raw facts -- that re-derivation silently failed whenever the specs
    # spelled it differently ("3-in-1" vs the canonical "3 in 1"), demoting a
    # genuine spec feature to marketing and making it consume the marketing
    # budget.
    from_spec: bool = False


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9&\- ]+", " ", text or "")).strip()


def _tokens_to_drop(
    brand: str, model: str, capacity: str, product_type: str, wattage: str = "",
) -> set[str]:
    """
    Words already represented by other parts of the Boss Rule formula.

    `wattage` (2026-08-10, review-flagged parity fix): dropped the same way
    `capacity` already is -- both now have a dedicated slot in build_name(),
    so a competitor title's own mention of either must not ALSO survive
    harvesting as a bogus "feature" term. Without this, a wattage phrased
    differently from the confirmed value ("700 Watts" vs. "700W") would
    slip through -- build_name()'s dedup only catches a byte-identical
    repeat, not a differently-worded one.
    """
    drop = set(_STOPWORDS)
    for part in (brand, model, capacity, product_type, wattage):
        for token in _normalise(part or "").lower().split():
            drop.add(token)
            drop.add(token.rstrip("s"))
    return drop


# "2 in 1", "3-in-1", "5 In 1" -- a standard, high-value appliance feature
# phrase that the general noise filter below would otherwise destroy
# completely: its digits are dropped as noise and "in" is a stopword, so
# every one of its words is discarded individually and the phrase can never
# form. Collapsed to a single indivisible token BEFORE that filter runs.
# Deliberately narrow: recognising this one well-known shape does not
# reopen the general digit gate, so prices/years/quantities are still
# dropped (see test_bare_digits_are_still_dropped_as_noise).
# Matches every real-world spelling of the feature -- "2 in 1", "3-in-1",
# "5 IN 1", "3In1", "3 - in - 1" -- so the same feature can never reach a
# title written two different ways. Separators are optional, which is what
# makes the no-space "3In1" form work.
_N_IN_ONE_RE = re.compile(r"\b(\d+)\s*-?\s*in\s*-?\s*1\b", re.IGNORECASE)


def _protect_n_in_one(text: str) -> tuple[str, dict[str, str]]:
    """
    Replaces each "N in 1" run with a single opaque token, returning the
    rewritten text and the token->original mapping needed to restore it.

    The token must be plain lowercase alphanumeric so it survives
    _normalise() (which strips punctuation) and the noise filter (not a
    stopword, not a bare digit, at least 2 characters).
    """
    restore: dict[str, str] = {}

    def _swap(match: re.Match[str]) -> str:
        token = f"ninonetoken{len(restore)}"
        restore[token] = f"{match.group(1)} in 1"
        return token

    protected = _N_IN_ONE_RE.sub(_swap, text or "")

    if restore:
        # A hyphen GLUED to the previous word ("Deluxe-2 in 1") survives the
        # substitution above untouched: _N_IN_ONE_RE's own \b starts matching
        # AT the digit, correctly, so the hyphen is simply text the regex
        # never looked at, and it ends up sitting directly against the new
        # sentinel token ("Deluxe-ninonetoken0"). Left alone, the noise
        # filter only strips punctuation from the OUTER edges of a word, this
        # hyphen is internal to it, and restoration below reproduces the
        # exact "Deluxe-2 in 1" bug (owner-reported, 2026-08-12).
        #
        # Fixed here, not by widening _N_IN_ONE_RE itself: that regex is
        # shared with _spec_feature_patterns(), which scans raw spec prose
        # for the same pattern -- changing its shape there broke six
        # spec-harvesting tests in an earlier attempt. This instead treats a
        # hyphen touching a token THIS CALL just created as the word
        # separator it visually reads as, splitting "Deluxe-ninonetoken0"
        # into "Deluxe" and "ninonetoken0" the same way a plain space would
        # -- exactly how the already-working "Deluxe 2 in 1" case behaves.
        token_pattern = "|".join(re.escape(token) for token in restore)
        protected = re.sub(rf"-(?=(?:{token_pattern})\b)", " ", protected)
        protected = re.sub(rf"(?<=\b(?:{token_pattern}))-", " ", protected)

    return protected, restore


def _restore_n_in_one(phrase: str, restore: dict[str, str]) -> str:
    for token, original in restore.items():
        phrase = re.sub(re.escape(token) + r"\b", original, phrase, flags=re.IGNORECASE)
    return phrase


def _spec_feature_patterns(spec_text: str) -> set[str]:
    """
    High-value title phrases recognised inside the product's own confirmed
    spec text -- see harvest_title_terms() for why this is deliberately a
    small pattern list rather than generic n-gram harvesting.

    Returns each match normalised to its canonical title form ("3-IN-1" and
    "3 in 1" both yield "3 in 1"), so the same feature never reaches a title
    written two different ways.
    """
    if not spec_text or not spec_text.strip():
        return set()
    return {f"{match.group(1)} in 1" for match in _N_IN_ONE_RE.finditer(spec_text)}


def _phrases_in_title(
    raw_title: str, drop: set[str], model_key: str,
) -> tuple[set[str], dict[str, str]] | None:
    """
    All 1-to-4-word sub-phrases survivng stopword/identity stripping in one
    title, or None when the title isn't verifiably about this model.
    """
    if not raw_title:
        return None
    if model_key and model_key not in re.sub(r"[^a-z0-9]", "", raw_title.lower()):
        return None


    # The sentinel is deliberately NOT restored in here. It stays in place
    # through the longest-wins redundancy filter in harvest_title_terms, so
    # "2 in 1" counts as ONE word there rather than three -- otherwise the
    # standalone term is deleted as a "subsequence" of any longer phrase that
    # contains it ("Deluxe 2 in 1"), which cancelled the spec-derived fix in
    # exactly the common case it exists for. Restored at term construction.
    raw_title, n_in_one_restore = _protect_n_in_one(raw_title)
    words = _normalise(raw_title).split()
    runs: list[list[str]] = []
    run: list[str] = []
    for word in words + [""]:
        key = word.lower().strip("-&")
        is_noise = (not key) or key in drop or key.isdigit() or len(key) < 2
        if is_noise:
            if run:
                runs.append(run)
                run = []
        else:
            # Append the CLEANED word, not the raw one. Stripping only decided
            # whether it was noise before -- the original spelling was kept, so
            # source text like "Deluxe-2 in 1" carried its hyphen into the
            # phrase and the exported title read "-2 in 1", which scans as
            # negative two (owner-reported, 2026-08-12).
            run.append(word.strip("-&"))

    # Emit every 1-to-4-word sub-phrase, not just whole runs. Sellers order and
    # pad their titles differently ("EZ Glass Door Bottom Load" vs "Glass Door
    # Bottom Load"), so whole-run matching almost never agrees and nothing
    # would ever reach the corroboration threshold. Real product phrases run
    # up to 4 words ("Glass Door Bottom Load"); a 3-word cap truncated them.
    phrases: set[str] = set()
    for candidate_run in runs:
        for size in (1, 2, 3, 4):
            for start in range(len(candidate_run) - size + 1):
                phrases.add(" ".join(candidate_run[start:start + size]))
    return phrases, n_in_one_restore


def harvest_title_terms(
    titles: Iterable[str],
    brand: str,
    model: str,
    capacity: str = "",
    product_type: str = "",
    min_frequency: int = 1,
    trusted_titles: Iterable[str] = (),
    wattage: str = "",
    spec_text: str = "",
) -> list[TitleTerm]:
    """
    Extracts candidate series/feature phrases from competitor titles, ranked by
    how many distinct titles use them.

    2026-08-09 (owner-directed): min_frequency default dropped from 2 to 1 --
    a single seller's title is now enough to corroborate a term, matching the
    same relaxation already applied to spec corroboration
    (ExtractionResult.confirmed_value). Cross-seller agreement is no longer
    required. The fact-matching gate in verify_terms() below is UNCHANGED and
    is now the only thing standing between a retailer's marketing phrase and
    the title: a word still has to appear in this product's own confirmed
    specs to be used, so an unrelated capability claim ("Inverter" on a
    non-inverter unit) is still rejected -- only the "needs a second seller
    to agree" bar is gone.

    Only titles that actually name the model are considered -- a title for a
    different product tells us nothing about this one. Consecutive surviving
    words are joined into phrases so "Luxury Ultra" stays together rather than
    becoming two unrelated tokens.

    `trusted_titles` -- title(s) from a source this system already treats as
    reliable for this specific product: source_type == "official" OR
    "trusted_secondary" (2026-08-09, widened 2026-08-10 -- owner-reported
    real marketing words missing from titles built off the SAME 1 official +
    1 trusted_secondary source already being scraped for facts; no new
    scraping was added to fix this, only which of the already-scraped titles
    get this trust). A phrase found there is marked `from_trusted_source=True`
    and treated as corroborated regardless of frequency: it does not need a
    second, unrelated seller to also use it, because both tiers are already
    trusted enough elsewhere in this system's design for a bounded judgment
    like this (official is authoritative alone; trusted_secondary is an
    owner-curated list -- see orchestrator.py's _brand_identity_ok for the
    identical reasoning applied to brand-identity matching). An unvetted
    `web` source's title stays in the plain `titles` argument and still needs
    to clear the fact-matching gate below. This is what lets a genuine
    marketing word ("Deluxe", "Handy") reach the title even when only one
    trusted seller ever wrote it down.
    """
    drop = _tokens_to_drop(brand, model, capacity, product_type, wattage)
    model_key = re.sub(r"[^a-z0-9]", "", (model or "").lower())

    phrase_counts: Counter[str] = Counter()
    trusted_phrases: set[str] = set()
    # Sentinel -> "N in 1" mappings from every source, merged so the tokens can
    # be restored once at the end, AFTER the redundancy filter has run.
    n_in_one_restore: dict[str, str] = {}
    for raw_title in trusted_titles:
        harvested = _phrases_in_title(raw_title, drop, model_key)
        if harvested:
            phrases, restore = harvested
            trusted_phrases |= phrases
            n_in_one_restore.update(restore)

    # The product's OWN confirmed spec text is a trusted channel too
    # (2026-08-11, owner-clarified). His real title "Anex AG-2098 Deluxe 2 in
    # 1 Vacuum Cleaner - 1500W" mixes a word found by searching other sellers
    # ("Deluxe") with one he derived from the product's own specs and
    # features ("2 in 1") -- the latter appears in NO seller's title, so
    # title-only harvesting could never produce it however well-verified it
    # was. Reading a phrase out of already-confirmed facts is not invention:
    # it is the same no-hallucination contract as the rest of the system.
    #
    # DELIBERATELY NARROW -- only recognised high-value feature PATTERNS, not
    # arbitrary n-grams. Spec text is prose, and phrases harvested from it
    # arrive marked trusted (auto-verified, no fact-match needed, because the
    # specs ARE the facts), so generic n-gram harvesting here would let any
    # stray four-word fragment of a spec paragraph into a title. One pattern
    # is recognised today, "N in 1" -- unambiguous, genuinely useful in a
    # title, and exactly the owner's reported case. Add further patterns
    # here only with a real example to justify each one.
    # Spec-derived phrases are tokenised the same way, so they collapse onto
    # the SAME sentinel as an identical phrase harvested from a title -- which
    # is what stops "2 in 1" appearing twice, and what lets the spec origin
    # win the fact_backed classification below.
    spec_phrases: set[str] = set()
    for spec_phrase in _spec_feature_patterns(spec_text):
        tokenised, restore = _protect_n_in_one(spec_phrase)
        n_in_one_restore.update(restore)
        spec_phrases.add(tokenised)
    trusted_phrases |= spec_phrases

    for raw_title in titles:
        harvested = _phrases_in_title(raw_title, drop, model_key)
        if harvested is None:
            continue
        phrases_in_title, restore = harvested
        n_in_one_restore.update(restore)
        # Count each phrase once per title, so one verbose seller cannot
        # manufacture a majority on its own.
        for phrase in phrases_in_title:
            phrase_counts[phrase] += 1

    # A trusted-only phrase (never repeated in any competitor title at all)
    # still needs to be counted at least once so it appears in the result set
    # below -- harvesting from trusted_titles alone must not depend on the
    # same phrase also showing up in `titles`.
    for phrase in trusted_phrases:
        if phrase not in phrase_counts:
            phrase_counts[phrase] = 1

    # Prefer the longest phrase: if "Glass Door" and "Glass" are equally common,
    # the fuller phrase is the real term and the fragment is noise.
    #
    # Compared as WORD SEQUENCES, not substrings: plain `in` matched across word
    # boundaries and wrongly deleted "Stainless Steel" because the unrelated
    # phrase "Fruit Juicer Stainless" happened to contain the letters.
    def is_subsequence(short_words: tuple[str, ...], long_words: tuple[str, ...]) -> bool:
        n = len(short_words)
        return any(long_words[i:i + n] == short_words for i in range(len(long_words) - n + 1))

    as_words = {p: tuple(p.lower().split()) for p in phrase_counts}
    redundant = {
        short
        for short, short_count in phrase_counts.items()
        for long, long_count in phrase_counts.items()
        if short != long
        and len(as_words[short]) < len(as_words[long])
        and is_subsequence(as_words[short], as_words[long])
        and long_count >= short_count
    }
    # A spec-derived phrase is never redundant. It is the product's own
    # confirmed feature, so being contained in some seller's longer marketing
    # phrase ("Deluxe 2 in 1") is no reason to drop it -- and dropping it was
    # what silently cancelled the spec-derived fix AND handed the surviving
    # compound to the marketing budget as a single unverified term.
    redundant -= spec_phrases

    terms = []
    for phrase, count in phrase_counts.most_common():
        if phrase in redundant:
            continue
        is_trusted = phrase in trusted_phrases
        from_spec = phrase in spec_phrases
        corroborated = is_trusted or count >= min_frequency
        terms.append(TitleTerm(
            # Sentinels are restored HERE, once, now that every phrase-level
            # comparison above is done.
            term=_restore_n_in_one(phrase, n_in_one_restore),
            frequency=count,
            corroborated=corroborated,
            verified=False,
            from_trusted_source=is_trusted,
            from_spec=from_spec,
            reason=(
                "found in this product's own confirmed specifications" if from_spec else
                "sourced from a trusted (official/trusted_secondary) source" if is_trusted else
                "" if count >= min_frequency else
                f"appears in only {count} title(s); needs {min_frequency}"
            ),
        ))
    return terms


def verify_terms(
    terms: list[TitleTerm],
    confirmed_facts: dict[str, str | None] | None = None,
    series: str | None = None,
) -> list[TitleTerm]:
    """
    Marks which corroborated terms are safe to put in a product title.

    ONE RULE, APPLIED TO EVERY CATEGORY: every word of the term must appear in
    the facts extraction confirmed for this product. No per-category vocabulary,
    no exceptions by product type -- an air conditioner, a juicer and a water
    dispenser are all judged the same way.

    Two allowances to that one rule:
      - `series`, the manufacturer's product line, matched against the
        extracted series value rather than the spec text: a series name
        ("Luxury Ultra", "Titan") identifies the model rather than asserting
        a capability, and it does not appear in the specifications.
      - `from_trusted_source` terms (2026-08-09, widened 2026-08-10,
        owner-directed): a marketing/series word from a trusted (official OR
        trusted_secondary) source's page ("Anex Deluxe...", "Anex Handy...")
        was never going to appear in a SPEC fact either -- "Deluxe" is not a
        capacity or a wattage. Requiring it to match confirmed_facts would
        reject it for a reason that has nothing to do with whether the claim
        is true. Both tiers are already trusted outright rather than checked
        against a fact list they were never going to be found in -- an
        unvetted `web` source's wording still has to clear that check.

    "UNKNOWN" facts count as absent, so a capability extraction could not
    confirm can never be justified by sellers repeating it.
    """
    facts = confirmed_facts or {}
    haystack = " ".join(
        str(v) for v in facts.values()
        if v and str(v).strip().upper() != "UNKNOWN"
    ).lower()
    series_key = (series or "").strip().lower()

    verified: list[TitleTerm] = []
    for term in terms:
        if not term.corroborated:
            verified.append(term)
            continue

        key = term.term.lower()

        # Fact backing is decided FIRST, before the trusted-source shortcut,
        # so a trusted source's wording that also happens to be a real
        # confirmed spec is correctly recorded as fact-backed rather than
        # being lumped in with unverifiable marketing padding (which
        # select_title_features caps).
        # A term harvested from the product's own confirmed specs IS a fact by
        # construction -- no string re-derivation needed (and re-deriving it
        # failed whenever the specs spelled it differently from the canonical
        # form, e.g. "3-in-1" vs "3 in 1").
        if term.from_spec:
            verified.append(term.model_copy(update={
                "verified": True, "fact_backed": True,
                "reason": "found in this product's own confirmed specifications",
            }))
            continue

        words = [w for w in re.split(r"[^a-z0-9&]+", key) if len(w) > 2]
        if words:
            supported = all(word in haystack for word in words)
        else:
            # Every word is too short to check individually. Match the phrase
            # as a whole, on WORD BOUNDARIES -- a raw substring test made
            # "5G" look confirmed by "has 5gb ram".
            supported = bool(key) and re.search(
                rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", haystack
            ) is not None

        if supported:
            verified.append(term.model_copy(update={
                "verified": True, "fact_backed": True,
                "reason": "every word confirmed by extracted facts",
            }))
            continue

        if series_key and key in series_key:
            verified.append(term.model_copy(update={
                "verified": True, "fact_backed": True,
                "reason": "matches the extracted product series",
            }))
            continue

        if term.from_trusted_source:
            verified.append(term.model_copy(update={
                "verified": True, "fact_backed": False,
                "reason": "sourced from a trusted (official/trusted_secondary) source",
            }))
            continue

        verified.append(term.model_copy(update={
            "verified": False,
            "reason": "not confirmed by extracted facts for this product; rejected",
        }))
    return verified


def select_title_features(
    terms: list[TitleTerm],
    max_terms: int | None = None,
) -> list[str]:
    """
    Returns the verified terms to pass into build_name(), most-corroborated first.

    Overlapping phrases are skipped: n-gram harvesting produces sibling phrases
    from the same words ("Glass Door Bottom" and "Door Bottom Load"), and taking
    both yielded the nonsense title "Door Bottom Load Glass Door Bottom Water
    Dispenser". Once a word has been used, any later phrase repeating it is
    dropped.

    `max_terms=None` (the default since 2026-08-11, owner-directed) means no
    count cap -- build_name()'s MAX_NAME_LENGTH is the only brake, and it
    already drops features last-first until the title fits. The previous
    hard cap of 2 could not build the owner's own feature-rich reference
    titles ("TCL 24SaveIN-AI-41 2 Ton T3 WiFi Smart DC Inverter Heat & Cool
    Split Air Conditioner" needs far more than two), and a count cap is the
    wrong tool anyway: what actually matters is the character budget, which
    is enforced where the title is assembled.
    """
    selected: list[str] = []
    used_words: set[str] = set()
    marketing_used = 0

    for term in terms:
        if not term.verified:
            continue
        words = {w for w in term.term.lower().split() if len(w) > 2}
        if words & used_words:
            continue
        if not term.fact_backed:
            # Marketing padding is capped independently of the overall limit,
            # and counted in WORDS -- a four-word phrase is four marketing
            # words in the title however it was grouped. See
            # MAX_MARKETING_WORDS. A phrase that would breach the budget is
            # skipped whole rather than truncated: half a marketing phrase
            # reads worse than none.
            if marketing_used + len(term.term.split()) > MAX_MARKETING_WORDS:
                continue
            marketing_used += len(term.term.split())
        selected.append(term.term)
        used_words |= words
        if max_terms is not None and len(selected) >= max_terms:
            break

    return selected
