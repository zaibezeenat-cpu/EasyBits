"""
Tests for the live-SKU snapshot: parsing, replacement, and the guard it feeds.

WHY THIS MATTERS MORE THAN MOST TESTS
-------------------------------------
WooCommerce matches imports by SKU. A CSV row carrying a SKU that already
exists does not create a product -- it OVERWRITES the live one. The snapshot is
the only thing the duplicate-SKU guard compares against, so an empty, stale or
partially-parsed snapshot means the guard silently passes everything.

Before this work the upload was faked in the frontend: it slept 1.5 seconds and
reported success while the table stayed empty.
"""
import pytest

from app.builders.sku_snapshot_parser import (
    MAX_UPLOAD_BYTES,
    SnapshotParseError,
    parse_sku_csv,
)


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


# --- Header handling --------------------------------------------------------

def test_parses_a_file_with_a_sku_header():
    parsed = parse_sku_csv(_csv("SKU\nKLU-12B03S\n18HRFN8\n"))
    assert parsed.had_header is True
    assert parsed.skus == ["KLU-12B03S", "18HRFN8"]


def test_parses_a_file_without_a_header():
    """
    A header-less file must not lose its first row. Guessing "the first row
    looks like a label" would silently drop a real SKU -- and a dropped SKU is
    a live product left unprotected.
    """
    parsed = parse_sku_csv(_csv("KLU-12B03S\n18HRFN8\n"))
    assert parsed.had_header is False
    assert parsed.skus == ["KLU-12B03S", "18HRFN8"]


def test_excel_byte_order_mark_does_not_corrupt_the_first_sku():
    """Excel prefixes a BOM; decoding it as data would mangle the first row."""
    raw = "﻿SKU\nKLU-12B03S\n".encode()
    parsed = parse_sku_csv(raw)
    assert parsed.had_header is True
    assert parsed.skus == ["KLU-12B03S"]


def test_multi_column_woocommerce_export_uses_the_first_column():
    parsed = parse_sku_csv(_csv("SKU,Name,Price\nKLU-12B03S,Kenwood AC,150000\n18HRFN8,Midea AC,220000\n"))
    assert parsed.skus == ["KLU-12B03S", "18HRFN8"]


# --- Rejections that protect the snapshot -----------------------------------

def test_empty_file_is_rejected():
    with pytest.raises(SnapshotParseError):
        parse_sku_csv(b"")


def test_file_with_only_a_header_is_rejected():
    """
    A header and no rows must fail loudly. Accepting it would replace a good
    snapshot with nothing and disable the guard entirely.
    """
    with pytest.raises(SnapshotParseError):
        parse_sku_csv(_csv("SKU\n"))


def test_oversized_file_is_rejected():
    with pytest.raises(SnapshotParseError):
        parse_sku_csv(b"x" * (MAX_UPLOAD_BYTES + 1))


def test_file_with_no_usable_skus_is_rejected():
    with pytest.raises(SnapshotParseError):
        parse_sku_csv(_csv("SKU\n\n\n"))


def test_product_names_are_skipped_and_reported():
    """
    Wrong-column uploads are common. A cell with spaces and no digits is a
    product NAME, not a SKU -- skipping it silently would hide the mistake.
    """
    parsed = parse_sku_csv(_csv("SKU\nKLU-12B03S\nKenwood Inverter Air Conditioner\n"))
    assert parsed.skus == ["KLU-12B03S"]
    assert parsed.skipped_rows == 1
    assert any("does not look like a SKU" in w for w in parsed.warnings)


def test_duplicates_are_collapsed_and_reported():
    parsed = parse_sku_csv(_csv("SKU\nKLU-12B03S\nKLU-12B03S\n18HRFN8\n"))
    assert parsed.skus == ["KLU-12B03S", "18HRFN8"]
    assert any("duplicate" in w.lower() for w in parsed.warnings)


def test_quoted_and_padded_values_are_cleaned():
    parsed = parse_sku_csv(_csv('SKU\n"KLU-12B03S"\n  18HRFN8  \n'))
    assert parsed.skus == ["KLU-12B03S", "18HRFN8"]


def test_blank_rows_are_skipped_not_stored():
    parsed = parse_sku_csv(_csv("SKU\nKLU-12B03S\n\n18HRFN8\n"))
    assert parsed.skus == ["KLU-12B03S", "18HRFN8"]


# --- Replacement semantics --------------------------------------------------

@pytest.mark.asyncio
async def test_replace_all_refuses_an_empty_list(monkeypatch):
    """
    The most dangerous possible write. Emptying the snapshot disables the guard
    completely, so it must never happen by accident.
    """
    from app.db.repositories.sku_snapshot import sku_snapshot_repo

    with pytest.raises(ValueError):
        await sku_snapshot_repo.replace_all([])

    with pytest.raises(ValueError):
        await sku_snapshot_repo.replace_all(["", "   "])


@pytest.mark.asyncio
async def test_replace_all_inserts_before_deleting(monkeypatch):
    """
    Order is the whole safety argument: DELETE-then-INSERT would leave a window
    with an EMPTY table, during which the guard passes everything. Inserting
    first means the overlap contains both old and new SKUs, so the guard
    over-blocks (recoverable) instead of under-blocking (destroys a listing).
    """
    from app.db.repositories import sku_snapshot as module

    operations: list[str] = []

    class FakeQuery:
        def upsert(self, *_a, **_k):
            operations.append("upsert")
            return self

        def select(self, *_a, **_k):
            return self

        def delete(self):
            operations.append("delete")
            return self

        def in_(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        async def execute(self):
            class Result:
                data = [{"sku": "OLD-SKU"}]
                count = 1
            return Result()

    class FakeDB:
        def table(self, _name):
            return FakeQuery()

    async def fake_get_supabase():
        return FakeDB()

    monkeypatch.setattr(module, "get_supabase", fake_get_supabase)

    await module.sku_snapshot_repo.replace_all(["NEW-SKU"])

    assert operations[0] == "upsert", "new SKUs must be written before anything is removed"
    assert "delete" in operations, "stale SKUs should still be pruned"
    assert operations.index("upsert") < operations.index("delete")
