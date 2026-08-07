"""
Specificity resolution in category inference.

THE PROBLEM
-----------
A taxonomy can hold a general category and a more specific variant of it:
"Chopper" and "Hand Chopper", "Oven" and "Microwave Oven". A title naming
the specific one ("Anex Hand Chopper") necessarily also contains the general
one's name, so BOTH match -- and infer_category treats >1 match as ambiguous
and returns None. The specific category can therefore never be inferred, no
matter how explicitly the title states it.

THE RULE
--------
When every match is a specificity chain -- one category's name is a strict
superset of another's words -- the most specific one wins. That is not a
guess: the title literally contains the extra word ("Hand"), so choosing
"Hand Chopper" is READING the title, not deducing beyond it.

Genuinely unrelated matches ("Blender" and "Chopper" both present) stay
ambiguous and still return None. Ambiguity is only resolved where the
taxonomy itself defines the relationship.
"""
from app.builders.input_adapter import infer_category

CHOPPERS = ["Chopper", "Hand Chopper"]


def test_the_specific_variant_wins_when_the_title_names_it():
    """THE HEADLINE CASE. Both match; the extra word is in the title."""
    assert infer_category("Anex Hand Chopper 1.5L", CHOPPERS) == "Hand Chopper"


def test_the_general_category_still_wins_when_nothing_narrows_it():
    """No specificity signal -> the general category, unchanged behaviour."""
    assert infer_category("Anex Electric Chopper 300W", CHOPPERS) == "Chopper"


def test_unrelated_categories_are_still_ambiguous():
    """
    The rule must NOT collapse real ambiguity. "Blender" and "Chopper" are not
    a specificity chain -- neither name contains the other -- so this stays
    None and routes to Manual Review, exactly as before.
    """
    assert infer_category("Anex Blender Chopper Combo", ["Blender", "Chopper"]) is None


def test_a_three_level_chain_picks_the_deepest():
    cats = ["Oven", "Microwave Oven", "Convection Microwave Oven"]
    assert infer_category("Dawlance Convection Microwave Oven 30L", cats) == (
        "Convection Microwave Oven"
    )


def test_a_substring_relationship_is_not_a_specificity_relationship():
    """
    The rule compares WORD SETS, not substrings, and the difference is a real
    correctness bug rather than a nicety.

    "Iron" is a substring of "Steam Ironing Board", so a substring-based rule
    would call the board a more specific kind of iron and silently file the
    product there. It is a different product. Word sets say {"iron"} is not a
    subset of {"steam","ironing","board"}, so this stays ambiguous and
    escalates -- the safe outcome.

    (Mutation-tested: swapping the subset check for substring containment must
    fail this test.)
    """
    both = ["Iron", "Steam Ironing Board"]
    assert infer_category("Philips Steam Ironing Board with Iron", both) is None


def test_a_single_match_is_unaffected():
    assert infer_category("Anex Vacuum Cleaner", ["Vacuum Cleaner", "Blender"]) == (
        "Vacuum Cleaner"
    )


def test_no_match_still_returns_none():
    assert infer_category("Anex Widget 9000", CHOPPERS) is None
