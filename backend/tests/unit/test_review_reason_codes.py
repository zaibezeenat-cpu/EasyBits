"""
Guards the failure-category <-> database-enum contract.

The Haier pilot found `warranty_conflict` (and by extension
`brand_casing_mismatch`, `production_lock_violation`) missing from the
`manual_review_reason_code` enum. The escalation INSERT crashed, the product's
status update never ran, and the product was stranded in QUEUED -- invisible.

These tests would have caught that before it reached a real run.
"""
import re
from pathlib import Path

import pytest

from app.models.failure import FailureCategory
from typing import get_args


_MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
_SCHEMA = _MIGRATIONS / "20260721000000_complete_schema.sql"


def _enum_values() -> set[str]:
    """Every value the manual_review_reason_code enum has across ALL migrations."""
    text = _SCHEMA.read_text(encoding="utf-8")
    block = re.search(r"CREATE TYPE manual_review_reason_code AS ENUM\s*\((.*?)\)", text, re.S)
    assert block, "enum definition not found in schema migration"
    values = set(re.findall(r"'([a-z_]+)'", block.group(1)))

    # Scan every migration for later `ADD VALUE` additions, so the guard keeps
    # working as new reason codes are introduced in new migration files -- not
    # pinned to a single hard-coded additions file.
    for sql in _MIGRATIONS.glob("*.sql"):
        for added in re.findall(
            r"ADD VALUE IF NOT EXISTS '([a-z_]+)'", sql.read_text(encoding="utf-8")
        ):
            values.add(added)
    return values


def test_every_failure_category_exists_in_the_enum():
    """
    The exact bug the pilot hit: a category the code can emit that the database
    enum does not know. Any such gap strands a product in QUEUED.
    """
    code_categories = set(get_args(FailureCategory))
    enum_values = _enum_values()

    missing = code_categories - enum_values
    assert not missing, (
        f"These failure categories are emitted by code but missing from the "
        f"manual_review_reason_code enum: {sorted(missing)}. Add them in a migration."
    )


def test_the_three_pilot_categories_are_now_covered():
    """Explicit lock on the specific values the pilot proved were missing."""
    enum_values = _enum_values()
    for value in ("warranty_conflict", "brand_casing_mismatch", "production_lock_violation"):
        assert value in enum_values, f"{value} must be in the enum (see the 2026-07-22 migration)"


@pytest.mark.asyncio
async def test_escalation_never_crashes_on_an_unknown_reason_code(monkeypatch):
    """
    Defence in depth: even if a future category is added to code before the
    migration lands, the escalation must fall back rather than crash and strand
    the product. Simulates the enum rejecting the value on the first insert.
    """
    from app.db.repositories import manual_review as module

    attempts: list[dict] = []

    class FakeQuery:
        def __init__(self, sink):
            self._sink = sink
            self._row = None

        def insert(self, row):
            self._row = row
            return self

        async def execute(self):
            attempts.append(self._row)
            # Reject only the first, enum-invalid attempt.
            if self._row["reason_code"] == "some_brand_new_code":
                raise Exception('invalid input value for enum manual_review_reason_code: "some_brand_new_code"')
            return type("R", (), {"data": [self._row]})()

    class FakeDB:
        def table(self, _name):
            return FakeQuery(attempts)

    async def fake_get_supabase():
        return FakeDB()

    monkeypatch.setattr(module, "get_supabase", fake_get_supabase)

    # Must not raise.
    await module.manual_review_repo.add(
        product_id="p1", batch_id="b1",
        reason_code="some_brand_new_code", reason_detail="details here",
    )

    assert len(attempts) == 2, "should try the real code, then retry with the fallback"
    assert attempts[1]["reason_code"] == "other"
    assert "[some_brand_new_code]" in attempts[1]["reason_detail"], "real code must be preserved in detail"
