import re

from app.models.extraction import ExtractionResult
from app.models.taxonomy import CategorySpecSchema

# All HTML attributes use SINGLE quotes (CSV Data Integrity rule 3): the CSV
# field delimiter is a double quote, so keeping doubles out of the markup
# removes any chance of a quoting interaction during import. Python string
# literals here therefore use double quotes on the outside.
_ROW = "    <tr style='border-bottom: 1px solid #eaeaea'>"
_TH = "text-align: left;padding: 8px 4px;color: #555555;font-weight: normal;vertical-align: top"
_TD = "padding: 8px 4px;color: #555555;vertical-align: top"

# A scraped bullet list ("Easy to use", "Manual Food Cutter", ...) often
# arrives already flattened to one string by the HTML-to-text cleanup
# upstream (BeautifulSoup's get_text() joins <li> siblings with no
# separator), and the Extractor is required to copy facts verbatim rather
# than rephrase them -- so a garbled "Easy to use.Manual Food
# Cutter.Quickly chops...onion, tomato," reaches this renderer completely
# unpunctuated. Owner-reported (real Anex AG-01 product). This is PURELY
# typographic cleanup of how the value DISPLAYS -- it never touches the
# stored citation value, so it is not "rewriting a fact": inserting a space
# a human obviously meant to be there, and dropping a comma with nothing
# after it, changes no word and asserts nothing new.
#
# Period is handled SEPARATELY from comma/semicolon/colon, and only fires
# when a LETTER follows -- never a digit -- so a decimal spec value like
# "9.5L" or "3.7V" is never touched (a digit-period-digit run must survive
# untouched, or a real capacity turns into a visibly wrong number).
# Comma/semicolon/colon carry no such risk in this codebase (decimals are
# always written with '.', never ','), so those fire before any alnum.
_MISSING_SPACE_AFTER_PERIOD = re.compile(r"\.(?=[A-Za-z])")
_MISSING_SPACE_AFTER_COMMA_SEMI_COLON = re.compile(r"([,;:])(?=[A-Za-z0-9])")
_DANGLING_TRAILING_PUNCTUATION = re.compile(r"[,;:]\s*$")


def _tidy_spec_value(value: str) -> str:
    """Cosmetic-only cleanup for display; see the module comment above."""
    text = value.strip()
    text = _MISSING_SPACE_AFTER_PERIOD.sub(". ", text)
    text = _MISSING_SPACE_AFTER_COMMA_SEMI_COLON.sub(r"\1 ", text)
    text = _DANGLING_TRAILING_PUNCTUATION.sub("", text).strip()
    return text


def render_specs_table(extraction: ExtractionResult, schema: CategorySpecSchema, warranty_phrase: str) -> str:
    """
    Renders the deterministic specs HTML table (Phase 1 §7.7).
    """
    html = [
        "<table class='shop_attributes' style='width: 100%;border-collapse: collapse;margin-bottom: 25px;font-size: 14px'>",
        "  <thead>",
        "    <tr style='border-bottom: 1px solid #eaeaea'>",
        "      <th style='text-align: left;padding: 8px 4px;width: 35%;color: #111111;font-family: var(--wd-title-font)'>SPECIFICATION</th>",
        "      <th style='text-align: left;padding: 8px 4px;color: #111111;font-family: var(--wd-title-font)'>DETAILS</th>",
        "    </tr>",
        "  </thead>",
        "  <tbody>",
    ]

    for field in schema.fields:
        value = extraction.confirmed_value(field.key)

        # Safe check for empty or unknown values to prevent them from printing
        if not value or str(value).strip().upper() == "UNKNOWN" or str(value).strip().upper() == "NOT AVAILABLE":
            continue

        value = _tidy_spec_value(str(value))

        html.append(_ROW)
        html.append(f"      <th style='{_TH}'>{field.label}</th>")
        html.append(f"      <td style='{_TD}'>{value}</td>")
        html.append("    </tr>")

    # Warranty row (always last). V3.0: wraps text in <strong> in addition to the
    # existing bold CSS -- additive, not a replacement, since the CSS styling was
    # already verified against a real working WooCommerce sample.
    html.append(_ROW)
    html.append(
        "      <th style='text-align: left;padding: 8px 4px;color: #555555;"
        "font-weight: bold;vertical-align: top'><strong>Warranty</strong></th>"
    )
    html.append(
        f"      <td style='padding: 8px 4px;color: #555555;vertical-align: top;"
        f"font-weight: bold'><strong>{warranty_phrase}</strong></td>"
    )
    html.append("    </tr>")

    html.append("  </tbody>")
    html.append("</table>")

    return "\n".join(html)
