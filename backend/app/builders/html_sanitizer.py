import html
import re

# V8.0 Production Lock: any of these wrapper tags immediately around an LSI
# keyword (or the focus keyword) must be stripped so Rank Math sees plain text.
_STRIPPABLE_TAGS = ["strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"]


def sanitize_html_fields(data: dict) -> dict:
    """
    Escapes HTML in specific fields for CSV safety.
    """
    fields_to_sanitize = ["short_description", "description", "specs_table_html"]
    for field in fields_to_sanitize:
        if field in data and data[field]:
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
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
