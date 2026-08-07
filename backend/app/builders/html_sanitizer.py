import html
import re
from decimal import Decimal, InvalidOperation

# V8.0 Production Lock: any of these wrapper tags immediately around an LSI
# keyword (or the focus keyword) must be stripped so Rank Math sees plain text.
_STRIPPABLE_TAGS = ["strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"]


def sanitize_html_fields(data: dict) -> dict:
    """
    Escapes HTML in specific fields for CSV safety.
    """
    fields_to_sanitize = ["short_description", "description", "specs_table_html"]
    for field in fields_to_sanitize:
        if data.get(field):
            data[field] = html.escape(data[field])
    return data


def strip_lsi_keyword_formatting(html_content: str, keywords: list[str]) -> str:
    """
    V8.0 Production Lock — Zero Tolerance LSI rule.

    Rank Math only detects LSI/focus keywords as plain text. If the Writer
    (or a template) ever wraps one of these exact strings in <strong>, <b>,
    or a header tag, this strips ONLY that tag pair immediately surrounding
    the keyword — the rest of the HTML is left untouched.

    Runs on raw (pre-html.escape) HTML, before sanitize_html_fields() escapes
    the string for CSV output.
    """
    if not html_content or not keywords:
        return html_content

    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        escaped_kw = re.escape(kw)
        for tag in _STRIPPABLE_TAGS:
            # Matches <tag ...>KEYWORD</tag> (allows attributes on the opening tag),
            # replacing it with the bare keyword text.
            pattern = re.compile(
                rf"<{tag}\b[^>]*>\s*({escaped_kw})\s*</{tag}>",
                re.IGNORECASE,
            )
            html_content = pattern.sub(r"\1", html_content)

    return html_content


def strip_newlines_for_csv(text: str) -> str:
    """
    V8.0 Production Lock — WooCommerce importer safety.

    Description / Short description columns MUST be single-line strings.
    Strip raw newline characters before injecting HTML into a CSV row.
    """
    if not text:
        return text
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")


# Characters that make a spreadsheet treat a cell as a formula rather than text.
_FORMULA_TRIGGERS = ("=", "+", "-", "@")


def _is_plain_number(text: str) -> bool:
    """True for a value a spreadsheet reads as a number, not a formula.

    `-1` and `+92` are data; `-1+1` and `+cmd|...` are not. Decimal draws the
    line in the same place the spreadsheet does.
    """
    try:
        Decimal(text)
    except InvalidOperation:
        return False
    return True


def neutralize_csv_formula(text: str) -> str:
    """Prefixes a formula-looking cell with `\'` so it is displayed, not executed.

    Excel and Google Sheets evaluate any cell whose text begins with `=`, `+`,
    `-` or `@` the moment the file is opened -- no click required. Operator
    sheets and scraped source text both reach this CSV, so a cell can carry
    `=cmd|\'/c calc\'!A1` or `=IMPORTXML(...)` without anyone having typed it.
    The leading apostrophe is the standard force-as-text marker: the
    spreadsheet consumes it and shows the original string.

    Numbers are deliberately exempt. The row ships `Published: -1` and
    `Position: 0`; escaping those turns them into text and breaks every
    WooCommerce import -- an over-broad guard would be the more damaging bug.

    Idempotent: an already-prefixed value starts with `\'`, which is not a
    trigger, so running this twice changes nothing.

    Args:
        text: The cell value.

    Returns:
        The value, prefixed with `\'` only if it would otherwise execute.
    """
    if not text:
        return text
    # Checked on the stripped value: readers differ on whether leading
    # whitespace disarms a formula, so assume it does not.
    stripped = text.lstrip()
    if not stripped.startswith(_FORMULA_TRIGGERS):
        return text
    if _is_plain_number(stripped):
        return text
    return "'" + text
