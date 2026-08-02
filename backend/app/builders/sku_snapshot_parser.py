"""
Parses an uploaded live-SKU export into a clean list of SKUs.

This feeds the duplicate-SKU guard, the last defence against a CSV import
silently OVERWRITING a live WooCommerce product. A parser that quietly drops
rows is therefore dangerous in a specific direction: every SKU it misses is a
live product left unprotected. It reports what it skipped rather than
discarding silently.
"""
import csv
import io
import re

from pydantic import BaseModel

# Guards against someone uploading a whole product export or an unrelated file.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_SKU_LENGTH = 128

# A WooCommerce export's SKU column is usually called exactly this.
_SKU_HEADER_NAMES = {"sku", "skus", "product sku", "item sku", "meta: sku"}


class ParsedSnapshot(BaseModel):
    skus: list[str]
    total_rows: int
    skipped_rows: int
    had_header: bool
    warnings: list[str] = []


class SnapshotParseError(ValueError):
    """Raised when the file cannot be parsed into a usable SKU list."""


def _looks_like_header(first_cell: str) -> bool:
    return first_cell.strip().strip('"').lower() in _SKU_HEADER_NAMES


def parse_sku_csv(raw: bytes, sku_column: int = 0) -> ParsedSnapshot:
    """
    Extracts SKUs from an uploaded CSV.

    Handles files with or without a header row: the first row is treated as a
    header only when its first cell is recognisably a SKU column name. Guessing
    based on "looks like a label" would silently drop a real SKU on a
    header-less file.

    Rejects the file outright rather than returning a partial list when it is
    empty, over-sized, or yields no usable SKUs -- a partial snapshot is worse
    than a failed upload, because it looks like protection while leaving most
    products exposed.
    """
    if not raw:
        raise SnapshotParseError("The uploaded file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise SnapshotParseError(
            f"File is too large ({len(raw) // 1024} KB). Maximum is {MAX_UPLOAD_BYTES // 1024 // 1024} MB."
        )

    try:
        # utf-8-sig strips the BOM Excel adds, which would otherwise corrupt the
        # first SKU (or hide the header) on every Excel-exported file.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except Exception as exc:  # pragma: no cover - defensive
            raise SnapshotParseError("Could not read the file as text. Is it a CSV?") from exc

    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    if not rows:
        raise SnapshotParseError("The file contains no rows.")

    had_header = False
    first_row = rows[0]
    if len(first_row) > sku_column and _looks_like_header(first_row[sku_column]):
        had_header = True
        rows = rows[1:]

    skus: list[str] = []
    skipped = 0
    warnings: list[str] = []

    for index, row in enumerate(rows, start=2 if had_header else 1):
        if len(row) <= sku_column:
            skipped += 1
            continue
        value = row[sku_column].strip().strip('"')
        if not value:
            skipped += 1
            continue
        if len(value) > MAX_SKU_LENGTH:
            skipped += 1
            warnings.append(f"Row {index}: SKU longer than {MAX_SKU_LENGTH} characters, skipped.")
            continue
        # A cell containing spaces and no digits is almost certainly a product
        # NAME, not a SKU -- a strong sign the wrong column was selected.
        if " " in value and not re.search(r"\d", value):
            skipped += 1
            warnings.append(f"Row {index}: '{value[:40]}' does not look like a SKU, skipped.")
            continue
        skus.append(value)

    if not skus:
        raise SnapshotParseError(
            "No valid SKUs found. Check that the first column contains SKUs."
        )

    unique = list(dict.fromkeys(skus))
    if len(unique) != len(skus):
        warnings.append(f"{len(skus) - len(unique)} duplicate SKU(s) in the file were collapsed.")

    if skipped:
        warnings.insert(0, f"{skipped} row(s) were skipped; {len(unique)} SKU(s) imported.")

    return ParsedSnapshot(
        skus=unique,
        total_rows=len(rows),
        skipped_rows=skipped,
        had_header=had_header,
        warnings=warnings[:10],
    )
