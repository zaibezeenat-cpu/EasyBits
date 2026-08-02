from app.models.extraction import ExtractionResult
from app.models.taxonomy import CategorySpecSchema

# All HTML attributes use SINGLE quotes (CSV Data Integrity rule 3): the CSV
# field delimiter is a double quote, so keeping doubles out of the markup
# removes any chance of a quoting interaction during import. Python string
# literals here therefore use double quotes on the outside.
_ROW = "    <tr style='border-bottom: 1px solid #eaeaea'>"
_TH = "text-align: left;padding: 8px 4px;color: #555555;font-weight: normal;vertical-align: top"
_TD = "padding: 8px 4px;color: #555555;vertical-align: top"


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
        value = extraction.confirmed_value(field.key) or "Not Available"
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
