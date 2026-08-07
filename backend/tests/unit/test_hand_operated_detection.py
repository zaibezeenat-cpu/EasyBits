"""
Recognising hand-operated appliances from the words in the title.

WHY
---
A hand chopper or hand blender has no motor and therefore no wattage. The
electric "Chopper"/"Blender" schemas mark wattage required, so a hand-operated
product matched to the electric category is routed to Manual Review for a fact
it can never have. Getting the category right is what avoids that.

The word "Hand" alone is not enough to match real titles. Anex's own page calls
the AG-01 a "Handy Pull Chopper" -- "Handy" is a different word from "Hand", and
"Pull" is the actual operating mechanism. These aliases list the vocabulary
Pakistani appliance listings really use for hand-operated food prep.

WHAT THIS IS NOT
----------------
Not inference. Every pattern here matches a word that is PRESENT in the title.
Nothing deduces a product's nature from a SKU or from model knowledge -- that
would be an unverifiable guess, which this codebase refuses everywhere else.
A title with no such word still resolves to the electric category, and the
operator's Category column override remains the way to correct it.
"""
import pytest

from app.builders.input_adapter import infer_category

CHOPPERS = ["Chopper", "Hand Chopper"]
BLENDERS = ["Blender", "Hand Blender"]
ALL_FOUR = ["Chopper", "Hand Chopper", "Blender", "Hand Blender"]


@pytest.mark.parametrize("title", [
    "Anex AG-01 Handy Pull Chopper",       # the real Anex product that started this
    "Handy Pull Chopper",                   # the title exactly as it appears in the sheet
    "Anex Hand Chopper 900ml",
    "Anex Manual Chopper 1.5L",             # "manual" still recognised
    "Kitchen Pull Chopper with 3 Blades",
    "Anex Hand Held Chopper",
    "Non Electric Chopper 650ml",
])
def test_hand_operated_choppers_resolve_to_hand_chopper(title: str):
    assert infer_category(title, CHOPPERS) == "Hand Chopper"


@pytest.mark.parametrize("title", [
    "Anex Hand Blender AG-123",
    "Anex Manual Hand Blender",
    "Westpoint Hand Held Blender",
])
def test_hand_operated_blenders_resolve_to_hand_blender(title: str):
    assert infer_category(title, BLENDERS) == "Hand Blender"


@pytest.mark.parametrize("title", [
    "Anex AG-2095 Chopper 300W",
    "Anex Electric Chopper 1.5L",
    "Anex Deluxe Chopper",
])
def test_a_plain_chopper_is_still_the_electric_category(title: str):
    """
    THE GUARD AGAINST OVER-MATCHING. A motorised chopper must keep requiring a
    wattage -- silently dropping that requirement across the whole category
    would be a far worse bug than the one being fixed.
    """
    assert infer_category(title, CHOPPERS) == "Chopper"


@pytest.mark.parametrize("title", [
    "Anex Blender 600W",
    "Anex Electric Blender 3 in 1",
])
def test_a_plain_blender_is_still_the_electric_category(title: str):
    assert infer_category(title, BLENDERS) == "Blender"


def test_a_hand_chopper_does_not_also_match_the_blender_family():
    """With all four categories live, the right one still wins outright."""
    assert infer_category("Anex Handy Pull Chopper", ALL_FOUR) == "Hand Chopper"
    assert infer_category("Anex Hand Blender", ALL_FOUR) == "Hand Blender"


def test_an_immersion_blender_is_not_a_hand_blender():
    """
    A deliberate exclusion, and the reason "hand held" is scoped rather than
    matched loosely. An immersion/stick blender is held in the hand but is very
    much motorised -- treating it as hand-operated would strip its wattage
    requirement. It stays on the electric category.
    """
    assert infer_category("Anex Immersion Hand Held Stick Blender 400W", BLENDERS) == (
        "Blender"
    )


def test_the_aliases_do_not_fire_without_the_category_in_the_taxonomy():
    """
    Aliases are additive, never a source of categories. If the operator has not
    created "Hand Chopper", a hand chopper falls back to the electric category
    rather than inventing a term that does not exist in the live store.
    """
    assert infer_category("Anex Handy Pull Chopper", ["Chopper"]) == "Chopper"
