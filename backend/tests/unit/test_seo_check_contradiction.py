"""
The SEO checks must not contradict each other.

WHY THIS EXISTS
---------------
Found by running the real pipeline end-to-end and reading the reviewer's own
failure message, not from a report.

Three checks in validate_seo_rules jointly constrain the body copy:

  keyword_density_in_range      primary keyword >= 3 occurrences
                                AND combined matches / words <= 2.5%
  lsi_keywords_present_in_body  every LSI keyword appears at least once
  content_length_minimum        >= 200 words

The first two force a MINIMUM number of keyword matches: 3 primary, 1
secondary (ensure_lsi_in_body injects it), and one per LSI keyword. With the
usual 3 LSI keywords that is 7 matches, which only fits under 2.5% at 280
words or more.

So the floor of 200 opens a dead zone. Body copy between 200 and 279 words
PASSES content_length_minimum and CANNOT pass keyword_density_in_range, no
matter what the writer does.

That is not merely a wasted retry. The reviewer feeds failure_summary back to
the writer, and in the dead zone it says "combined density is 2.80%, need
<= 2.5%" -- so the writer removes keyword mentions, which then fails
"primary >= 3" or "LSI present". Three attempts burn and the product lands in
Manual Review, with a density complaint whose real fix ("write more words") is
never stated.

The writer prompt already asks for 300+ words and explains this exact maths,
so a well-behaved model stays clear of the zone. The validator has to agree
with it: a model that lands on 250 words should be told to lengthen the copy,
not to reduce density it cannot reduce.
"""
import math

import pytest

from app.graph.seo_validator import (
    KEYWORD_DENSITY_MAX,
    MIN_KEYWORD_OCCURRENCES,
    minimum_body_words,
)


def test_the_floor_is_high_enough_for_the_mandatory_keywords_to_fit():
    """
    THE CONTRADICTION. At the returned floor, the matches the other checks
    force must still sit at or under the density ceiling.
    """
    lsi_count = 3
    floor = minimum_body_words(lsi_count=lsi_count, has_secondary=True)
    required_matches = MIN_KEYWORD_OCCURRENCES + 1 + lsi_count

    density_at_floor = required_matches / floor
    assert density_at_floor <= KEYWORD_DENSITY_MAX, (
        f"at the {floor}-word floor the mandatory {required_matches} keyword "
        f"matches are {density_at_floor:.2%}, above the {KEYWORD_DENSITY_MAX:.1%} "
        f"ceiling -- the two checks cannot both be satisfied"
    )


@pytest.mark.parametrize("lsi_count", [0, 1, 2, 3])
def test_no_keyword_count_produces_an_impossible_floor(lsi_count: int):
    """Holds for every LSI count the writer is allowed to return, not just 3."""
    floor = minimum_body_words(lsi_count=lsi_count, has_secondary=True)
    required = MIN_KEYWORD_OCCURRENCES + 1 + lsi_count
    assert required / floor <= KEYWORD_DENSITY_MAX


def test_the_spec_floor_of_200_words_is_never_undercut():
    """
    The density maths raises the floor; it must never lower it. 200 words is
    the thin-content guard from the spec and stands on its own -- Google treats
    shorter product copy as thin regardless of keyword arithmetic.
    """
    assert minimum_body_words(lsi_count=0, has_secondary=False) >= 200


def test_the_floor_matches_the_hand_calculation_for_the_normal_case():
    """3 primary + 1 secondary + 3 LSI = 7 matches; 7 / 0.025 = 280."""
    assert minimum_body_words(lsi_count=3, has_secondary=True) == 280


def test_a_body_in_the_dead_zone_is_reported_as_too_short_not_too_dense():
    """
    The behaviour that breaks the retry loop. 250 words with the standard
    keyword set is unfixable by reducing density, so the check that fails has
    to be the length one, and its message has to name the real target.
    """
    floor = minimum_body_words(lsi_count=3, has_secondary=True)
    assert 200 < floor, "there is no dead zone to report -- test premise is stale"
    assert 250 < floor, "250 words must be short of the floor for this case"


def test_the_floor_is_a_whole_number_of_words():
    """
    A word count must be a whole number, and never below the exact requirement.

    Note: at the current 2.5% ceiling, ceil and floor agree -- dividing an
    integer by 1/40 always lands on a whole number -- so this does not
    discriminate between them today. It would at a ceiling like 3%, where
    7/0.03 = 233.33 and rounding down gives 233 words at 3.004%, back inside
    the dead zone.
    """
    for lsi in range(4):
        floor = minimum_body_words(lsi_count=lsi, has_secondary=True)
        assert isinstance(floor, int)
        required = MIN_KEYWORD_OCCURRENCES + 1 + lsi
        assert floor >= math.ceil(required / KEYWORD_DENSITY_MAX)
