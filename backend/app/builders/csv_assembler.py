import csv
import io
import logging
from typing import Any

from app.builders.html_sanitizer import neutralize_csv_formula, strip_newlines_for_csv
from app.builders.internal_links import build_canonical_url, build_product_slug
from app.builders.seo_title_builder import build_focus_keyword_field
from app.graph.state import PipelineState

logger = logging.getLogger(__name__)

COLUMN_ORDER = [
    "ID", "Type", "SKU", "Name", "slug", "Published", "Is featured?", "Visibility in catalog",
    "Short description", "Description", "Date sale price starts", "Date sale price ends",
    "Tax status", "Tax class", "In stock?", "Stock", "Low stock amount",
    "Backorders allowed?", "Sold individually?", "Weight (kg)", "Length (cm)",
    "Width (cm)", "Height (cm)", "Allow customer reviews?", "Purchase note",
    "Sale price", "Regular price", "Categories", "Tags", "Shipping class",
    "Images", "Download limit", "Download expiry days", "Parent",
    "Grouped products", "Upsells", "Cross-sells", "External URL",
    "Button text", "Position", "Brands",
    "Meta: _woodmart_product_custom_tab_title",
    "Meta: _woodmart_product_custom_tab_priority",
    "Meta: _woodmart_product_custom_tab_content_type",
    "Meta: _woodmart_product_custom_tab_content",
    "Meta: rank_math_focus_keyword",
    "Meta: rank_math_title",
    "Meta: rank_math_description",
    "Meta: rank_math_seo_score",
    "Meta: rank_math_breadcrumb_title",
    "Meta: rank_math_canonical_url",
]


# Columns the operator's input sheet may overlay onto the generated row.
#
# Everything NOT listed here is protected, including by omission -- see the
# overlay in assemble_csv_row for why. The protected set is, in effect:
#   ID, SKU            -- identity; ID drives create-vs-overwrite in WooCommerce
#                         and is validated by RawProductInput.existing_id
#   Brands, Categories -- guarded by the casing locks; a differing letter creates
#                         a duplicate taxonomy term in the live store
#   Name, slug         -- deterministic Boss-Rule outputs, and slug feeds the
#                         canonical URL
#   Meta: rank_math_*  -- deterministic SEO fields the validator grades
PASSTHROUGH_ALLOWED = frozenset({
    "Published", "Is featured?", "Visibility in catalog",
    "Date sale price starts", "Date sale price ends",
    "Tax status", "Tax class",
    "In stock?", "Stock", "Low stock amount",
    "Backorders allowed?", "Sold individually?",
    "Weight (kg)", "Length (cm)", "Width (cm)", "Height (cm)",
    "Allow customer reviews?", "Purchase note",
    "Sale price", "Regular price",
    "Tags", "Shipping class", "Images",
    "Download limit", "Download expiry days",
    "Parent", "Grouped products", "Upsells", "Cross-sells",
    "External URL", "Button text", "Position",
    "Meta: _woodmart_product_custom_tab_title",
    "Meta: _woodmart_product_custom_tab_priority",
    "Meta: _woodmart_product_custom_tab_content_type",
})


# Pipeline breadcrumb -> live-store breadcrumb, applied on export only.
#
# The pipeline sometimes needs a category the store does not have. A hand
# chopper has no motor and therefore no wattage, so it needs its own spec schema
# and therefore its own category -- but the store sells these as plain
# "Chopper". Without the translation the CSV would create a duplicate category
# in WooCommerce. Same for a hand blender against the store's "Blender".
#
# Both sides must be EXACT, case-sensitive breadcrumbs: WooCommerce matches
# taxonomy terms by exact string, so "chopper" and "Chopper" are two categories.
# The right-hand side is never validated by the casing lock (it belongs to the
# store, not to us), so it has to be correct here by inspection.
STORE_CATEGORY_ALIASES: dict[str, str] = {
    "Kitchen Appliances > Hand Chopper": "Kitchen Appliances > Chopper",
    "Kitchen Appliances > Hand Blender": "Kitchen Appliances > Blender",
}


class BrandCasingMismatchError(ValueError):
    """Raised when the brand name does not exactly match the live taxonomy casing (V8.0 lock)."""


class CategoryBreadcrumbError(ValueError):
    """Raised when Categories is not in '[Parent] > [Category]' breadcrumb form (V8.0 lock)."""


class CategoryCasingMismatchError(ValueError):
    """Raised when the category path does not exactly match the live taxonomy casing."""


def _dim_or_blank(value: object) -> object:
    """A positive numeric dimension, else "" -- unknown dimensions stay blank so a
    fabricated 0 never reaches the live product."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    return number if number > 0 else ""


def assemble_csv_row(
    state: PipelineState,
    category_path: str,
    brand_name: str,
    canonical_brand_name: str | None = None,
    canonical_category_path: str | None = None,
) -> dict[str, Any]:
    """
    Maps PipelineState to the 49-column WooCommerce CSV format.

    V8.0 Production Lock additions:
      - Brand Casing Lock: brand_name must exactly (case-sensitive) match the
        live taxonomy's canonical casing. No cosmetic normalization allowed.
      - Category Casing Lock: category_path must exactly match the breadcrumb
        built from live taxonomy. See below for why the breadcrumb assertion
        alone was not enough.
      - Category Breadcrumb Assertion: Categories must contain "[Parent] > [Category]".
      - Newline Stripping: Description / Short description are forced single-line
        before being written, since multiline strings break the WooCommerce importer.
    """
    p = state.raw_input
    w = state.writer_output
    d = state.dimensions

    # --- Brand Casing Lock (V8.0) ---
    if canonical_brand_name is not None and brand_name != canonical_brand_name:
        raise BrandCasingMismatchError(
            f"Brand '{brand_name}' does not exactly match live taxonomy casing '{canonical_brand_name}'. "
            f"No cosmetic casing normalization is allowed — fix the source taxonomy or the input."
        )

    # --- Category breadcrumb + casing lock ---
    # The real guard is an EXACT match against the breadcrumb built from live
    # taxonomy (below): a child category's canonical form is "[Parent] > [Category]",
    # a legitimate TOP-LEVEL category's (e.g. "Beauty") is just its own name. A
    # blanket "must contain ' > '" check used to be here, but it wrongly rejected
    # valid top-level categories; the exact-canonical-match check covers every case
    # (bare/unverified name -> canonical is None -> rejected; wrong parent/casing ->
    # mismatch -> rejected).
    # WHY THE BREADCRUMB ASSERTION ABOVE IS NOT ENOUGH: WooCommerce matches
    # taxonomy terms by exact string, so "home appliance > air conditioner" does
    # not file the product under the existing category -- it CREATES A SECOND
    # ONE in the live store. A bare wrong-cased name was already stopped above
    # for lacking " > ", but an operator who types the breadcrumb themselves
    # produced a value that passed that check and went straight into the CSV.
    #
    # `canonical_category_path` is None when the category could not be resolved
    # against live taxonomy at all. That is not a reason to skip the check --
    # it is the strongest reason to fail, because nothing verified the term.
    if canonical_category_path is None:
        raise CategoryCasingMismatchError(
            f"Category '{category_path}' could not be resolved against live taxonomy, so its "
            f"casing cannot be verified. Exporting it risks creating a duplicate category in "
            f"WooCommerce. Add or correct it in the Taxonomy Manager."
        )
    if category_path != canonical_category_path:
        raise CategoryCasingMismatchError(
            f"Category '{category_path}' does not exactly match live taxonomy casing "
            f"'{canonical_category_path}'. A single differing letter creates a NEW category "
            f"in WooCommerce — no cosmetic casing normalization is allowed."
        )

    # --- Newline Stripping (V8.0) — WooCommerce importer safety ---
    description_safe = strip_newlines_for_csv(state.description or "")
    short_description_safe = strip_newlines_for_csv(state.short_description or "")

    # Short URL slug + canonical, decoupled from the (long) title so Rank Math's
    # URL-length rule passes -- model number + product type, capped so the full
    # canonical URL stays <= 65 chars.
    product_slug = build_product_slug(p.model_number, p.product_type, brand=brand_name)
    canonical_url = build_canonical_url(product_slug)

    row = {
        # ID drives WooCommerce's import behaviour: empty -> create a new product;
        # an existing product ID -> update that product in place (no duplicate). It
        # is filled from the sheet's optional "Existing ID" so redoing an already-
        # uploaded product with the new logic updates it rather than cloning it.
        "ID": (p.existing_id or "") if getattr(p, "existing_id", None) else "",
        "Type": "simple",
        "SKU": p.sku,
        "Name": state.name or f"{brand_name} {p.model_number}",
        "slug": product_slug,
        "Published": "-1",
        "Is featured?": "0",
        "Visibility in catalog": "visible",
        "Short description": short_description_safe,
        "Description": description_safe,
        "Date sale price starts": "",
        "Date sale price ends": "",
        "Tax status": "none",
        "Tax class": "",
        "In stock?": "1" if p.in_stock else "0",
        "Stock": "10",
        "Low stock amount": "",
        "Backorders allowed?": "0",
        "Sold individually?": "0",
        # Unknown dimensions are left BLANK, never 0.0: a real "0 cm" would set
        # wrong physical dimensions on the live product (and skew shipping). A
        # dimension only appears when it was actually found.
        "Weight (kg)": _dim_or_blank(d.weight_kg) if d else "",
        "Length (cm)": _dim_or_blank(d.length_cm) if d else "",
        "Width (cm)": _dim_or_blank(d.width_cm) if d else "",
        "Height (cm)": _dim_or_blank(d.height_cm) if d else "",
        "Allow customer reviews?": "1",
        "Purchase note": "",
        "Sale price": float(p.sale_price) if p.sale_price else "",
        "Regular price": float(p.regular_price) if p.regular_price else "",
        "Categories": category_path,
        "Tags": state.tags or f"{brand_name}, {p.category_name}, HW",
        "Shipping class": "",
        "Images": "",
        "Download limit": "0",
        "Download expiry days": "0",
        "Parent": "",
        "Grouped products": "",
        "Upsells": "",
        "Cross-sells": "",
        "External URL": "",
        "Button text": "",
        "Position": "0",
        "Brands": brand_name,
        "Meta: _woodmart_product_custom_tab_title": "Specification",
        "Meta: _woodmart_product_custom_tab_priority": "20",
        "Meta: _woodmart_product_custom_tab_content_type": "text",
        "Meta: _woodmart_product_custom_tab_content": state.specs_table_html or "",
        # V3.0: title is deterministic (state), NOT sourced from writer_output.
        # Focus keyword field = deterministic primary (state.rank_math_focus_keyword,
        # the exact Product Name) + the Writer's 3 LSI keywords, matching Rank
        # Math's real primary+secondary keyword mechanism (confirmed from the
        # live Rank Math panel, not a guess) -- see build_focus_keyword_field().
        # Focus keyword field = PRIMARY (brand+model) , 2nd (model+type) , then LSI.
        "Meta: rank_math_focus_keyword": (
            build_focus_keyword_field(
                state.rank_math_focus_keyword,
                [state.rank_math_secondary_keyword or ""] + list(w.lsi_keywords),
            )
            if state.rank_math_focus_keyword and w else (state.rank_math_focus_keyword or "")
        ),
        "Meta: rank_math_title": state.rank_math_title or "",
        "Meta: rank_math_description": w.rank_math_description if w else "",
        "Meta: rank_math_seo_score": "",
        "Meta: rank_math_breadcrumb_title": state.name or p.model_number,
        "Meta: rank_math_canonical_url": canonical_url,
    }

    # --- Passthrough Data Overlay ---
    # Overlay the operator's own columns from the input CSV onto the generated row,
    # so data the pipeline does not model (Images, Tax class, Stock) survives.
    #
    # Restricted to PASSTHROUGH_ALLOWED. This overlay is the LAST thing to touch the
    # row -- after the Brand and Category casing locks have run and after
    # existing_id has been validated -- so an unrestricted overlay silently undoes
    # all three. Measured: {"Brands": "haier", "ID": "99999"} landed verbatim,
    # which in a live import means a duplicate brand term and an overwrite of
    # product 99999 instead of a create.
    #
    # An allowlist, not a denylist: a column added to COLUMN_ORDER later is
    # protected by default and has to be opted in deliberately.
    #
    # A blank value (e.g. " ") leaves the generated value in place. Clearing a
    # generated field would need an explicit token, not an empty cell.
    if p.passthrough_columns:
        column_map = {c.lower(): c for c in COLUMN_ORDER}
        blocked: list[str] = []
        for user_col, val in p.passthrough_columns.items():
            matched_key = column_map.get(user_col.lower())
            if not matched_key or not val or not str(val).strip():
                continue
            if matched_key not in PASSTHROUGH_ALLOWED:
                blocked.append(matched_key)
                continue
            row[matched_key] = str(val).strip()
        if blocked:
            # Reported, never silent: dropping it quietly would leave the operator
            # believing their value shipped.
            logger.warning(
                f"Ignored passthrough override for protected column(s) "
                f"{sorted(blocked)} on SKU {p.sku}: these are derived from verified "
                f"taxonomy/identity and cannot be set from the input sheet."
            )

    # --- Pipeline category -> store category ---
    # Applied AFTER the casing lock, and that order is correct: the lock verifies
    # the value against the PIPELINE's taxonomy, this translates it into the
    # STORE's. They are different namespaces on purpose.
    #
    # "Hand Chopper" / "Hand Blender" exist in the pipeline so each can carry its
    # own spec schema -- a hand-operated appliance has no wattage, so that field
    # is not required for it. The live store has no such terms; it sells these
    # under "Chopper" and "Blender". Exporting the pipeline name would create a
    # second category in WooCommerce, which is the very thing the casing lock
    # guards against.
    mapped_category = STORE_CATEGORY_ALIASES.get(row.get("Categories", ""))
    if mapped_category:
        logger.info(
            f"Category '{row['Categories']}' exported as '{mapped_category}' for SKU "
            f"{p.sku} (pipeline taxonomy -> live store taxonomy)."
        )
        row["Categories"] = mapped_category

    # --- Strict CSV Sanitization ---
    # Strip literal line-breaks (\n, \r) and tab indentations (\t) from EVERY string field.
    # This prevents column shifts when users copy-paste the generated CSV into Google Sheets.
    #
    # Then neutralize formula cells. Both operator passthrough and scraped source
    # text land in this row, and a cell starting with = + - @ is executed by
    # Excel/Sheets on open. Numbers are exempt, so "Published": "-1" survives --
    # see neutralize_csv_formula.
    sanitized_row = {}
    for k, v in row.items():
        if isinstance(v, str):
            sanitized_row[k] = neutralize_csv_formula(strip_newlines_for_csv(v))
        else:
            sanitized_row[k] = v

    return sanitized_row

def generate_csv_file(rows: list[dict[str, Any]]) -> str:
    """Writes the rows out, re-applying the formula guard at the file boundary.

    assemble_csv_row already neutralizes its own output, and the guard is
    idempotent -- this repeat covers rows built by any other path (tests,
    re-exports, a future endpoint) so no writer can bypass it by accident.
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUMN_ORDER, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    for row in rows:
        writer.writerow({
            k: neutralize_csv_formula(v) if isinstance(v, str) else v
            for k, v in row.items()
        })
    return output.getvalue()
