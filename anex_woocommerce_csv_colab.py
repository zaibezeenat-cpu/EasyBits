# Google Colab Python Script for Generating 51-Column WooCommerce CSV for Anex Products
# Run this cell in Google Colab to convert anex_total_products_details.csv into a 51-column WooCommerce import CSV.

import csv
import re
import io
from decimal import Decimal, InvalidOperation

# ----------------------------------------------------
# 1. 51-Column WooCommerce Order Definition
# ----------------------------------------------------
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

def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")

def clean_price(val: str) -> str:
    if not val: return ""
    digits = "".join(c for c in str(val) if c.isdigit() or c == ".")
    return str(float(digits)) if digits else ""

def strip_newlines(text: str) -> str:
    if not text: return ""
    return re.sub(r"\s+", " ", text).strip()

def process_anex_csv(input_csv_path: str, output_csv_path: str):
    with open(input_csv_path, mode="r", encoding="utf-8-sig") as infile:
        reader = csv.DictReader(infile)
        rows = list(reader)

    out_rows = []
    for r in rows:
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
        warranty = (r.get("Warranty") or "2-Year Brand Official Warranty").strip()
        images = (r.get("Image_URLs") or "").strip()

        # Category mapping
        tag = (r.get("Tags") or "").lower()
        if "chopper" in title.lower() or "slicer" in title.lower() or "cutter" in title.lower():
            cat_path = "Kitchen Appliances > Chopper"
            cat_slug = "chopper"
            cat_name = "Chopper"
        elif "blender" in title.lower() or "juicer" in title.lower() or "grinder" in title.lower():
            cat_path = "Kitchen Appliances > Blender"
            cat_slug = "blender"
            cat_name = "Blender"
        elif "insect" in title.lower() or "killer" in title.lower():
            cat_path = "Home Appliances > Insect Killer"
            cat_slug = "insect-killer"
            cat_name = "Insect Killer"
        elif "kitchen" in tag or "food" in title.lower():
            cat_path = "Kitchen Appliances"
            cat_slug = "kitchen-appliances"
            cat_name = "Kitchen Appliances"
        else:
            cat_path = "Home Appliances"
            cat_slug = "home-appliances"
            cat_name = "Home Appliances"

        product_slug = f"{slugify(sku)}-{slugify(cat_name)}" if sku else slugify(title)
        
        # Build HTML description
        why_buy_html = (
            f"<div style='background: #fffdf5; border: 1px solid #fce8b3; border-radius: 12px; padding: 20px 25px; margin: 25px 0;'>"
            f"<h3 style='color: #f7a800; margin-top: 0; margin-bottom: 12px; font-size: 18px;'>🛒 Why Buy from Kiachahiye?</h3>"
            f"<p style='margin: 0; line-height: 1.7; font-size: 14px;'>Get the unit at the best price in Pakistan with <strong>official Anex warranty</strong>, "
            f"<strong>genuine product guarantee</strong>, and <strong>open parcel then pay</strong>. Upgrade your home appliance setup today!</p></div>"
        )
        
        faq_html = (
            f"<h3 style='color: #561491; border-bottom: 2px solid #F7A800; padding-bottom: 8px; margin-top: 35px; margin-bottom: 20px; font-size: 20px;'>Frequently Asked Questions (FAQs)</h3>"
            f"<div style='display: flex; flex-direction: column; gap: 12px; margin-bottom: 25px;'>"
            f"<details style='background: #fff; border: 1px solid #eae2f8; border-left: 4px solid #561491; border-radius: 6px; padding: 15px 18px; cursor: pointer;'>"
            f"<summary style='font-size: 15px; color: #561491; font-weight: 600;'>Q1: Is the {title} covered by official warranty?</summary>"
            f"<p style='margin-top: 12px; color: #444; font-size: 14px;'><strong>A:</strong> Yes, it comes with official {warranty}.</p></details>"
            f"<details style='background: #fff; border: 1px solid #eae2f8; border-left: 4px solid #561491; border-radius: 6px; padding: 15px 18px; cursor: pointer;'>"
            f"<summary style='font-size: 15px; color: #561491; font-weight: 600;'>Q2: Where can I buy genuine {title} online?</summary>"
            f"<p style='margin-top: 12px; color: #444; font-size: 14px;'><strong>A:</strong> You can order authentic {title} from Kiachahiye.com with Open Parcel Then Pay.</p></details>"
            f"</div>"
        )

        link_block = (
            f"<p style='margin-top: 25px; font-size: 14px;'>Browse more "
            f"<a href='https://kiachahiye.com/product-category/{cat_slug}/' style='color: #561491; text-decoration: underline;'>{cat_name}</a> &nbsp;|&nbsp; "
            f"View all <a href='https://kiachahiye.com/brand/anex/' style='color: #561491; text-decoration: underline;'>Anex</a> products &nbsp;|&nbsp; "
            f"Official brand site: <a href='https://www.anex.pk' style='color: #561491; text-decoration: underline;' target='_blank'>Anex Official</a></p>"
        )

        description = (
            f"<h2 style='color: #561491; border-left: 5px solid #F7A800; padding-left: 12px; font-size: 22px; margin-bottom: 15px;'>{title}</h2>"
            f"<p>The {title} offers premium quality, durability, and reliable everyday performance in Pakistan.</p>"
            f"{why_buy_html}{faq_html}{link_block}"
        )

        short_description = (
            f"<p><strong>{title}</strong> with official <strong>{warranty}</strong>. "
            f"Get genuine product at best price in Pakistan with open parcel then pay service at Kiachahiye.</p>"
        )

        specs_table = (
            f"<table class='shop_attributes'>"
            f"<tr><th>Brand</th><td>Anex</td></tr>"
            f"<tr><th>Model</th><td>{sku}</td></tr>"
            f"<tr><th>Warranty</th><td>{warranty}</td></tr>"
            f"</table>"
        )

        focus_kw = f"anex {sku.lower()} {cat_name.lower()}".strip()

        row = {
            "ID": "",
            "Type": "simple",
            "SKU": sku,
            "Name": title,
            "slug": product_slug,
            "Published": "-1",
            "Is featured?": "0",
            "Visibility in catalog": "visible",
            "Short description": strip_newlines(short_description),
            "Description": strip_newlines(description),
            "Date sale price starts": "",
            "Date sale price ends": "",
            "Tax status": "none",
            "Tax class": "",
            "In stock?": "1",
            "Stock": "10",
            "Low stock amount": "",
            "Backorders allowed?": "0",
            "Sold individually?": "0",
            "Weight (kg)": "",
            "Length (cm)": "",
            "Width (cm)": "",
            "Height (cm)": "",
            "Allow customer reviews?": "1",
            "Purchase note": "",
            "Sale price": sale_price,
            "Regular price": reg_price,
            "Categories": cat_path,
            "Tags": f"Anex, {cat_name}, Home Appliances",
            "Shipping class": "",
            "Images": images,
            "Download limit": "0",
            "Download expiry days": "0",
            "Parent": "",
            "Grouped products": "",
            "Upsells": "",
            "Cross-sells": "",
            "External URL": "",
            "Button text": "",
            "Position": "0",
            "Brands": "Anex",
            "Meta: _woodmart_product_custom_tab_title": "Specification",
            "Meta: _woodmart_product_custom_tab_priority": "20",
            "Meta: _woodmart_product_custom_tab_content_type": "text",
            "Meta: _woodmart_product_custom_tab_content": specs_table,
            "Meta: rank_math_focus_keyword": focus_kw,
            "Meta: rank_math_title": f"{title} Price in Pakistan | Kiachahiye",
            "Meta: rank_math_description": f"Buy official {title} in Pakistan at best price. Features {warranty} & open parcel delivery at Kiachahiye.",
            "Meta: rank_math_seo_score": "85",
            "Meta: rank_math_breadcrumb_title": title,
            "Meta: rank_math_canonical_url": f"https://kiachahiye.com/product/{product_slug}/",
        }
        out_rows.append(row)

    with open(output_csv_path, mode="w", encoding="utf-8-sig", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=COLUMN_ORDER)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Successfully processed {len(out_rows)} products into {output_csv_path}")

# Run conversion
process_anex_csv("anex_total_products_details.csv", "anex_woocommerce_51col_export.csv")
