"""
Fast Direct Anex 51-Column WooCommerce CSV Generator.

Processes all products in anex_total_products_details.csv directly through the
EasyBits backend architecture without web scraping overhead, outputting the exact
51-column WooCommerce import CSV ready for live site upload in seconds.
"""
import asyncio
import csv
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.builders.csv_assembler import COLUMN_ORDER, assemble_csv_row
from app.builders.description_merger import render_template_b
from app.builders.html_sanitizer import strip_newlines_for_csv
from app.builders.input_adapter import infer_category
from app.builders.internal_links import (
    build_canonical_url,
    build_link_block,
    build_product_slug,
    category_url,
)

from app.builders.tag_generator import build_tags
from app.db.repositories.brands import brands_repo
from app.db.repositories.categories import categories_repo
from app.models.raw_input import RawProductInput
from app.graph.state import PipelineState
from app.models.writer_output import FAQPair, WriterOutput


def clean_price(val: str) -> Decimal | None:
    if not val:
        return None
    digits = "".join(c for c in str(val) if c.isdigit() or c == ".")
    try:
        return Decimal(digits) if digits else None
    except InvalidOperation:
        return None


def extract_bullets_from_text_or_html(text: str, html: str) -> list[str]:
    bullets = []
    if text and text.strip():
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for l in lines:
            if len(l) > 3 and not l.lower().startswith("http"):
                bullets.append(l)
    if not bullets and html:
        # Extract <li> or paragraph text
        clean = re.sub(r"<[^>]+>", "\n", html)
        lines = [l.strip() for l in clean.splitlines() if l.strip()]
        for l in lines:
            if len(l) > 3 and not l.lower().startswith("http"):
                bullets.append(l)
    return bullets[:5] if bullets else ["Official Brand Quality", "Easy and convenient operation", "Durable construction", "Energy efficient design"]


def build_writer_output_from_raw(title: str, text: str, html: str, warranty: str, sku: str, cat_display: str) -> WriterOutput:
    bullets = extract_bullets_from_text_or_html(text, html)
    hero_p = f"The {title} offers reliable performance, superior durability, and modern kitchen convenience. Designed for everyday home use in Pakistan."
    
    faqs = [
        FAQPair(
            question=f"Is the {title} easy to use and clean?",
            answer=f"Yes, the {title} features an ergonomic design making it extremely simple to operate and clean."
        ),
        FAQPair(
            question=f"Where can I buy genuine {title} online in Pakistan?",
            answer=f"You can order authentic {title} directly from Kiachahiye.com with Open Parcel Then Pay service."
        ),
        FAQPair(
            question=f"What makes the {title} a great choice for your home?",
            answer=f"The {title} combines robust build quality, energy efficiency, and official brand support."
        ),
        FAQPair(
            question=f"How long does delivery take for {title} in Pakistan?",
            answer=f"Kiachahiye delivers {title} across Pakistan within 2 to 4 business days."
        ),
        FAQPair(
            question="What is the official warranty?",
            answer=f"This product comes with {warranty}."
        )
    ]
    
    cat_lower = cat_display.lower()
    sku_lower = sku.lower()
    lsi_1 = f"anex {sku_lower} {cat_lower}".strip()
    lsi_2 = f"anex {sku_lower} {cat_lower} price in pakistan".strip()
    lsi_3 = f"best anex {cat_lower} in pakistan".strip()
    lsi_4 = f"buy original anex {sku_lower}".strip()
    lsi_5 = f"anex {cat_lower} official warranty".strip()

    # Ensure all 5 keywords are distinct and non-empty
    lsi_list = list(dict.fromkeys([lsi_1, lsi_2, lsi_3, lsi_4, lsi_5]))

    return WriterOutput(
        hero_heading=f"Premium Performance: {title}",
        hero_paragraph=hero_p,
        feature_headings=[f"Key Features of {title}", "Everyday Convenience"],
        feature_texts=[
            f"Equipped with high quality components, the {title} delivers consistent results every time.",
            "Designed for quick maintenance, easy storage, and maximum user convenience."
        ],
        features_bullets=bullets,
        faqs=faqs,
        short_desc_feature_1=bullets[0] if len(bullets) > 0 else "Official Brand Quality",
        short_desc_feature_2=bullets[1] if len(bullets) > 1 else "Durable construction",
        short_desc_feature_3=bullets[2] if len(bullets) > 2 else "Easy operation",
        rank_math_description=f"Buy official {title} in Pakistan at best price. Features {warranty} & open parcel delivery at Kiachahiye.",
        lsi_keywords=lsi_list,
        alt_text_1=f"{title} front view",
        alt_text_2=f"{title} features",
        alt_text_3=f"{title} packaging"
    )


async def main():
    start_time = time.perf_counter()
    input_file = backend_dir.parent / "anex_total_products_details.csv"
    output_file = backend_dir.parent / "anex_products_woocommerce_51col.csv"

    if not input_file.exists():
        print(f"Error: Input file {input_file} not found.")
        sys.exit(1)

    print(f"Reading input data from {input_file.name}...")
    rows = list(csv.DictReader(open(input_file, encoding="utf-8-sig")))
    print(f"Loaded {len(rows)} product rows.")

    known_brands = await brands_repo.get_active_names()
    known_categories, category_parents = await categories_repo.get_active_names_and_parents()
    all_cats = await categories_repo.list()
    top_level_cats = [c.name for c in all_cats if not c.parent_id]

    csv_rows: list[dict] = []
    success_count = 0
    skip_count = 0

    for i, r in enumerate(rows, 1):
        sku = (r.get("Input_Model_Code") or r.get("Official_SKU") or r.get("Original_Model / Code") or "").strip()
        raw_title = (r.get("Official_Model_Title") or r.get("Original_Item Description") or f"Anex {sku}").strip()
        if sku and not raw_title.startswith(sku) and not f" {sku}" in raw_title:
            title = f"Anex {sku} {raw_title}"
        elif not raw_title.lower().startswith("anex"):
            title = f"Anex {raw_title}"
        else:
            title = raw_title

        reg_price = clean_price(r.get("Regular_Price")) or clean_price(r.get("Original_PRICE"))
        sale_price = clean_price(r.get("Sale_Price")) or clean_price(r.get("Original_PRICE")) or reg_price

        if not reg_price and sale_price:
            reg_price = sale_price
        elif not sale_price and reg_price:
            sale_price = reg_price

        if not sku or not sale_price or reg_price is None:
            print(f"Row {i}: Skipping {sku or raw_title} (missing price/sku)")
            skip_count += 1
            continue

        warranty = (r.get("Warranty") or "2-Year Brand Official Warranty").strip()
        desc_text = r.get("Clean_Description_Text") or ""
        desc_html = r.get("Full_Description_HTML") or ""
        image_urls = (r.get("Image_URLs") or "").strip()

        # Category resolution
        cat_name = infer_category(
            product_name=title,
            known_categories=known_categories,
            top_level_categories=top_level_cats
        )
        if not cat_name:
            cat_name = "Kitchen Appliances" if "kitchen" in (r.get("Tags") or "").lower() else "Home Appliances"

        parent_cat = category_parents.get(cat_name)
        if cat_name.strip().lower() == "manual chopper":
            cat_display = "Chopper"
            if not parent_cat: parent_cat = "Kitchen Appliances"
        else:
            cat_display = cat_name

        if parent_cat:
            cat_path = f"{parent_cat} > {cat_display}"
        else:
            cat_path = cat_display

        # Build Writer Output & Description HTML
        wo = build_writer_output_from_raw(title, desc_text, desc_html, warranty, sku, cat_display)
        focus_kw = f"anex {sku.lower()} {cat_display.lower()}".strip()
        
        body_html = render_template_b(
            writer_output=wo,
            product_name=title,
            focus_keyword=focus_kw,
            brand_name="Anex"
        )
        
        official_domain = "https://www.anex.pk"
        link_block = build_link_block(
            brand_name="Anex",
            category_name=cat_name,
            parent_category=parent_cat,
            official_brand_domain=official_domain
        )
        
        full_description = f"{body_html}\n{link_block}"
        
        # Build short description
        bullets_html = "".join(f"<li>{b}</li>" for b in wo.features_bullets[:4])
        short_desc = (
            f"<p><strong>{title}</strong> with official <strong>{warranty}</strong>. "
            f"Get genuine quality at best price in Pakistan with open parcel delivery.</p>"
            f"<ul>{bullets_html}</ul>"
        )

        slug = build_product_slug(sku, cat_display, brand="Anex")
        canonical_url = build_canonical_url(slug)

        # Meta SEO fields
        meta_title = f"{title} Price in Pakistan | Kiachahiye"
        if len(meta_title) > 60:
            meta_title = f"{title} | Kiachahiye"
        
        meta_desc = (
            f"Buy official {title} in Pakistan at best price. "
            f"Features genuine {warranty}, fast shipping & open parcel then pay at Kiachahiye."
        )

        def build_rich_spec_table(
            brand: str,
            model: str,
            title: str,
            category: str,
            warranty: str,
            bullets: list[str],
            text: str,
            html_content: str,
        ) -> str:
            rows = [
                ("Brand", brand),
                ("Model / Code", model),
            ]
            
            clean_type = re.sub(r"^anex\s*", "", title, flags=re.IGNORECASE)
            clean_type = re.sub(r"^" + re.escape(model) + r"\s*", "", clean_type, flags=re.IGNORECASE)
            clean_type = re.sub(r"^ag-\d+[a-z]*\s*", "", clean_type, flags=re.IGNORECASE).strip()
            
            rows.append(("Appliance Type", clean_type or category))

            combined_info = f"{title} {text} {html_content} {' '.join(bullets)}"
            combined_lower = combined_info.lower()

            is_manual = any(k in combined_lower for k in [
                "manual", "handy", "pull chopper", "string operated", "french fries cutter", "slicer", "cutter", "hand operated"
            ]) and not any(k in combined_lower for k in ["motor", "220v", "240v", "50hz", "60hz", "watt", "watts"])

            if is_manual:
                rows.append(("Operation Type", "Manual (Non-Electric)"))
            else:
                # Power / Wattage
                p_match = re.search(r"(\d+\s*(?:W|Watts|Watt))\b", combined_info, re.IGNORECASE)
                if p_match:
                    rows.append(("Power Consumption", p_match.group(1).upper()))

                # Voltage & Frequency
                v_match = re.search(r"(\d+(?:-\d+)?\s*(?:Volt|Volts|V))\b", combined_info, re.IGNORECASE)
                f_match = re.search(r"(\d+(?:/\d+)?\s*Hz)\b", combined_info, re.IGNORECASE)
                if v_match:
                    val = v_match.group(1)
                    if f_match:
                        val += f" / {f_match.group(1)}"
                    rows.append(("Operating Voltage", val))
                elif f_match:
                    rows.append(("Frequency", f_match.group(1)))

            # Capacity / Size
            c_match = re.search(r"(\d+(?:\.\d+)?\s*(?:L|Ltr|Liter|Liters|Gallon|KG|Ton))\b", combined_info, re.IGNORECASE)
            if c_match:
                rows.append(("Capacity / Size", c_match.group(1)))

            # Key Features from bullets
            if bullets:
                feat_count = 1
                for bullet in bullets:
                    b_clean = bullet.strip().rstrip(".")
                    if len(b_clean) > 3 and not any(k in b_clean.lower() for k in ["220v", "50hz", "2 years warranty", "200w", "300w"]):
                        rows.append((f"Key Feature {feat_count}", b_clean))
                        feat_count += 1
                        if feat_count > 4:
                            break

            # Warranty
            rows.append(("Official Warranty", f"<strong>{warranty}</strong>"))

            table_rows = []
            for label, value in rows:
                table_rows.append(
                    f"<tr style='border-bottom: 1px solid #eaeaea;'>"
                    f"<th style='text-align: left; padding: 10px 8px; width: 35%; color: #444444; font-weight: 500; vertical-align: top;'>{label}</th>"
                    f"<td style='padding: 10px 8px; color: #333333; vertical-align: top;'>{value}</td>"
                    f"</tr>"
                )

            table_html = (
                f"<table class='shop_attributes' style='width: 100%; border-collapse: collapse; margin-bottom: 25px; font-size: 14px;'>"
                f"<thead><tr style='border-bottom: 1px solid #eaeaea;'>"
                f"<th style='text-align: left; padding: 10px 8px; color: #561491; font-weight: 600; font-family: var(--wd-title-font);'>SPECIFICATION</th>"
                f"<th style='text-align: left; padding: 10px 8px; color: #561491; font-weight: 600; font-family: var(--wd-title-font);'>DETAILS</th>"
                f"</tr></thead>"
                f"<tbody>{''.join(table_rows)}</tbody>"
                f"</table>"
            )
            return strip_newlines_for_csv(table_html)

        specs_html = build_rich_spec_table("Anex", sku, title, cat_display, warranty, wo.features_bullets, desc_text, desc_html)

        # Create PipelineState for assembler
        import uuid
        state = PipelineState(
            product_id=uuid.uuid4(),
            batch_id=uuid.uuid4(),
            raw_input=RawProductInput(
                sku=sku,
                model_number=sku,
                brand_name="Anex",
                category_name=cat_name,
                regular_price=reg_price,
                sale_price=sale_price,
                warranty_override=warranty,
                official_url=r.get("Product_URL") or "https://www.anex.pk",
                source_details=desc_text,
                user_overrides={"Images": f"{sku.replace(' ', '')}.jpg"}
            ),
            writer_output=wo,
            description=full_description,
            short_description=short_desc,
            name=title,
            rank_math_focus_keyword=focus_kw,
            rank_math_title=meta_title,
            rank_math_description=meta_desc,
            tags=build_tags("Anex", cat_display),
            specs_table_html=specs_html
        )

        row = assemble_csv_row(
            state=state,
            category_path=cat_path,
            brand_name="Anex",
            canonical_brand_name="Anex",
            canonical_category_path=cat_path
        )
        csv_rows.append(row)
        success_count += 1

    # Write output CSV with UTF-8 BOM and QUOTE_ALL to ensure Google Sheets and WooCommerce
    # parse all 51 columns with zero column shifting or cell merging.
    with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMN_ORDER, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(csv_rows)

    elapsed = time.perf_counter() - start_time
    print(f"\n==========================================")
    print(f"SUCCESSFULLY GENERATED 51-COLUMN WOOCOMMERCE CSV!")
    print(f"Total Products Generated: {success_count}")
    print(f"Skipped Rows: {skip_count}")
    print(f"Total Time: {elapsed:.2f} seconds ({elapsed / max(1, success_count):.3f}s per product)")
    print(f"Output File: {output_file}")
    print(f"==========================================")


if __name__ == "__main__":
    asyncio.run(main())
