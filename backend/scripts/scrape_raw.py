"""
STEP 1: raw product data from the web, as a CSV. No writing, no review.

    python scripts/scrape_raw.py input.csv raw.csv
    python scripts/scrape_raw.py input.csv raw.csv --limit 3

Input is the SAME CSV bulk_run.py takes (parsed by the same code), so there
is no second format to keep in sync. Category is inferred from the product
Name when the sheet has no Category column -- deterministic, no LLM.

WHAT THIS GIVES YOU that bulk_run.py does not: the COMPLETE raw description
and specification text exactly as the site wrote it, the real product and
in-description image URLs, and the price -- all with the source URL behind
each one. bulk_run.py flattens all of that into one truncated text blob for
the Extractor and you never see it again.

WHAT IT DELIBERATELY DOES NOT DO: no Writer, no Reviewer, no 51-column
WooCommerce CSV -- that is Step 2 (bulk_run.py), unchanged. It creates no
batch and no product rows either, so it can be run as often as you like
without touching the database.

ONE SOURCE PER PRODUCT, NEVER MERGED. Text from two sites is never
concatenated -- that is what made earlier output unreadable. The best
source wins the row and the rest are listed in Source URLs for reference.
"""
import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.builders.name_builder import build_name  # noqa: E402
from app.builders.title_terms import (  # noqa: E402
    harvest_title_terms,
    select_title_features,
    verify_terms,
)
from app.models.raw_input import RawProductInput  # noqa: E402
from app.scraping.orchestrator import scrape_product  # noqa: E402
from scripts.bulk_run import _build_inputs  # noqa: E402

# Matches the codebase's own sentinel (see specs_renderer.py, which filters
# exactly these two) so a missing value can never render as a literal spec
# value on a live product page.
UNKNOWN = "UNKNOWN"

COLUMNS = (
    "S.NO", "SKU", "Brand", "Model Number", "Category", "Title",
    "Online Price", "Warranty",
    "Description Raw", "Specification Raw",
    "Product Images", "Description Images",
    "Best Source", "Best Source URL",
    "Result", "Sources Found", "Source URLs", "Source Types",
)

# Trust order for picking the ONE source that fills this row. Mirrors
# fact_corroboration._TIER_RANK rather than inventing a second ranking.
_TIER_RANK = {"official": 3, "trusted_secondary": 2, "web": 1, "user_estimate": 0}


@dataclass
class RawRow:
    sku: str
    brand: str
    model_number: str
    category: str
    warranty: str
    result: str = "ok"
    title: str = ""
    price: str = ""
    description: str = ""
    specification: str = ""
    product_images: list[str] = field(default_factory=list)
    description_images: list[str] = field(default_factory=list)
    best_source_type: str = ""
    best_source_url: str = ""
    source_urls: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)

    def to_row(self, index: int) -> dict[str, str]:
        return {
            "S.NO": str(index),
            "SKU": self.sku,
            "Brand": self.brand,
            "Model Number": self.model_number,
            "Category": self.category or UNKNOWN,
            "Title": self.title or UNKNOWN,
            "Online Price": self.price or UNKNOWN,
            "Warranty": self.warranty or UNKNOWN,
            "Description Raw": self.description or UNKNOWN,
            "Specification Raw": self.specification or UNKNOWN,
            "Product Images": " | ".join(self.product_images) or UNKNOWN,
            "Description Images": " | ".join(self.description_images) or UNKNOWN,
            "Best Source": self.best_source_type or UNKNOWN,
            "Best Source URL": self.best_source_url or UNKNOWN,
            "Result": self.result,
            "Sources Found": str(len(self.source_urls)),
            "Source URLs": " | ".join(self.source_urls),
            "Source Types": " | ".join(self.source_types),
        }


def _pick_best(docs: list[dict]) -> dict | None:
    """
    The ONE source that fills this row.

    Trust first (official > trusted_secondary > web), then -- among sources
    at the SAME tier -- the one carrying the most raw text. Trust always wins
    across tiers, so a long retailer page never displaces the brand's own
    page; the length comparison only breaks ties between equally-trusted
    retailers, where there is no other principled way to choose.

    A source that yielded no usable text at all is skipped entirely, so an
    official page that 404'd or returned an empty shell does not win the row
    and leave it blank -- the next-best source that DID return something
    takes it instead.
    """
    def usable_text(doc: dict) -> str:
        return (doc.get("raw_description_text")
                or doc.get("raw_specification_text")
                or doc.get("content")
                or "")

    candidates = [d for d in docs if usable_text(d).strip()]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda d: (_TIER_RANK.get(d.get("source_type", ""), 0), len(usable_text(d))),
    )


def _build_title(raw: RawProductInput, docs: list[dict], best: dict | None) -> str:
    """
    Best-effort title using the SAME Boss-Rule builders the real pipeline
    uses -- and no LLM: harvest_title_terms only needs titles plus a fact
    dict, and the raw specification text stands in for the latter here.

    Labelled best-effort on purpose: without the Extractor there are no
    per-field confirmed specs, so this is a preview of the title bulk_run.py
    would build, not a replacement for it.
    """
    spec_text = (best or {}).get("raw_specification_text", "") or ""
    trusted = [
        t for d in docs if d.get("source_type") in ("official", "trusted_secondary")
        for t in d.get("candidate_titles", [])
    ]
    competitor = [t for d in docs for t in d.get("candidate_titles", [])]
    try:
        harvested = harvest_title_terms(
            titles=competitor, trusted_titles=trusted,
            brand=raw.brand_name, model=raw.model_number,
            product_type=raw.product_type or raw.category_name,
            spec_text=spec_text,
        )
        features = select_title_features(
            verify_terms(harvested, {"raw_specs": spec_text})
        )
        return build_name(
            raw.brand_name, "", raw.model_number,
            raw.product_type or raw.category_name, features=features,
        )
    except Exception:  # noqa: BLE001 -- a title is a nice-to-have, never fatal
        return ""


async def _scrape_one(raw: RawProductInput) -> RawRow:
    out = RawRow(
        sku=raw.sku, brand=raw.brand_name, model_number=raw.model_number,
        category=raw.category_name, warranty=raw.warranty_override or "",
    )
    try:
        scraped = await scrape_product(raw.brand_name, raw.model_number)
        if "failure" in scraped:
            out.result = scraped["failure"].category
            return out

        docs = scraped.get("scraped_data", [])
        out.source_urls = [str(d.get("url", "")) for d in docs]
        out.source_types = [str(d.get("source_type", "")) for d in docs]

        best = _pick_best(docs)
        if best is None:
            out.result = "no_usable_content"
            return out

        out.best_source_type = str(best.get("source_type", ""))
        out.best_source_url = str(best.get("url", ""))
        # Every text field comes from THIS one source -- never mixed with
        # another site's, which is what made earlier output contradict itself.
        out.description = best.get("raw_description_text") or best.get("content") or ""
        out.specification = best.get("raw_specification_text") or ""
        out.product_images = list(best.get("raw_images") or [])
        out.description_images = list(best.get("raw_description_images") or [])
        out.price = str(best.get("raw_price") or "")
        out.title = _build_title(raw, docs, best)
    except Exception as e:  # noqa: BLE001 -- one bad product must not stop the run
        out.result = f"error: {type(e).__name__}: {e}"
    return out


async def run(input_path: str, output_path: str, limit: int | None) -> None:
    rows = list(csv.DictReader(open(input_path, encoding="utf-8-sig")))
    print(f"Read {len(rows)} rows from {input_path}")

    inputs, skipped = await _build_inputs(rows)
    print(f"Resolved {len(inputs)} products; {len(skipped)} could not be resolved.")
    for s in skipped:
        print("  SKIP", s)
    if limit is not None:
        inputs = inputs[:limit]
        print(f"Limited to the first {len(inputs)}.")
    if not inputs:
        print("Nothing to scrape.")
        return

    results: list[RawRow] = []
    for i, raw in enumerate(inputs, start=1):
        row = await _scrape_one(raw)
        results.append(row)
        print(f"  [{i}/{len(inputs)}] {row.sku}: {row.result} "
              f"({len(row.source_urls)} source(s), best={row.best_source_type or '-'}, "
              f"desc={len(row.description)} chars, "
              f"specs={'yes' if row.specification else 'no'}, "
              f"imgs={len(row.product_images)}+{len(row.description_images)})")

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for i, row in enumerate(results, start=1):
            writer.writerow(row.to_row(i))

    ok = [r for r in results if r.result == "ok"]
    with_specs = [r for r in ok if r.specification]
    print("\n===== DONE =====")
    print(f"Wrote {len(results)} row(s) to {output_path}")
    print(f"  {len(ok)} scraped, {len(with_specs)} of those with a real spec table")
    for row in results:
        if row.result != "ok":
            print(f"  {row.sku}: {row.result}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Step 1: raw per-product data as CSV (no writing, no review)."
    )
    ap.add_argument("input", help="input products CSV (same format as bulk_run.py)")
    ap.add_argument("output", help="output raw-data CSV")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N products (quick check)")
    args = ap.parse_args()
    asyncio.run(run(args.input, args.output, args.limit))


if __name__ == "__main__":
    main()
