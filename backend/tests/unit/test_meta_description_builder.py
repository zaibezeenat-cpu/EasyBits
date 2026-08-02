"""
Tests for deterministic meta-description assembly.

The pilot proved the LLM cannot hit a character window (it produced 185 vs the
150-160 target). These lock that the builder ALWAYS lands in 151-155 and always
satisfies the four anchor rules, whatever the writer's middle phrase looks like.
"""
import pytest

from app.builders.meta_description_builder import (
    MAX_LEN,
    MIN_LEN,
    build_meta_description,
)

CTA = "Buy the best 9 Cu Ft refrigerator in Pakistan today."
WARRANTY = "Compressor: 10 Year; Electronics: 3 Year; Other parts: 1 Year"


def _check_anchors(meta: str, keyword: str):
    assert MIN_LEN <= len(meta) <= MAX_LEN, f"length {len(meta)} outside window: {meta!r}"
    assert meta.startswith(keyword), "must begin with the focus keyword"
    assert meta.rstrip().endswith(CTA), "must end with the exact CTA"


def test_haier_real_case_lands_in_window():
    keyword = "Haier HRF-246 IPGA 9 Cu Ft Green Glass Door Smart Inverter Refrigerator"
    meta = build_meta_description(keyword, WARRANTY, CTA, selling_phrase="Deep-freezing inverter fridge")
    _check_anchors(meta, keyword)
    # Warranty numbers present.
    assert "10" in meta and "3" in meta and "1" in meta


def test_overlong_middle_is_trimmed_to_fit():
    keyword = "Haier HRF-246 IPGA Refrigerator"
    huge = "word " * 100
    meta = build_meta_description(keyword, WARRANTY, CTA, selling_phrase=huge)
    _check_anchors(meta, keyword)


def test_empty_middle_is_padded_up_to_the_floor():
    keyword = "Anex AG-123 Blender"
    meta = build_meta_description(keyword, "1 Year Warranty", CTA, selling_phrase="")
    _check_anchors(meta, keyword)


def test_warranty_numbers_are_always_present():
    keyword = "Dawlance DW-131 Microwave Oven"
    meta = build_meta_description(keyword, "2 Year Brand Warranty", CTA, selling_phrase="Fast even cooking")
    assert "2" in meta
    _check_anchors(meta, keyword)


def test_unbuildable_when_keyword_plus_cta_exceed_window():
    """A pathologically long product name cannot fit; the caller must escalate."""
    keyword = "Haier " + "Super Ultra Mega Deluxe " * 8 + "Refrigerator"
    with pytest.raises(ValueError):
        build_meta_description(keyword, WARRANTY, CTA, selling_phrase="x")


def test_no_warranty_still_builds():
    keyword = "GFC Pedestal Fan Model X"
    meta = build_meta_description(keyword, "", CTA, selling_phrase="Powerful airflow for any room size")
    _check_anchors(meta, keyword)
