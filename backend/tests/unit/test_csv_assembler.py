from decimal import Decimal
from uuid import uuid4

from app.builders.csv_assembler import COLUMN_ORDER, assemble_csv_row, generate_csv_file
from app.graph.state import PipelineState
from app.models.raw_input import RawProductInput


def test_assemble_csv_row_columns():
    raw_input = RawProductInput(
        sku="TEST-SKU-1",
        model_number="MODEL-123",
        brand_name="Haier",
        category_name="AC",
        product_type="Air Conditioner",
        regular_price=Decimal(100),
        sale_price=Decimal(90)
    )
    
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=raw_input,
        name="Haier MODEL-123 AC",
        tags="Haier, AC, HW",
        short_description="<ul><li>F1</li></ul>",
        description="Full Desc",
        specs_table_html="<table></table>",
        resolved_warranty_phrase="1-Year"
    )
    
    row = assemble_csv_row(
        state, "Electronics > AC", "Haier",
        canonical_category_path="Electronics > AC",
    )
    
    assert row["SKU"] == "TEST-SKU-1"
    assert row["Name"] == "Haier MODEL-123 AC"
    assert row["Categories"] == "Electronics > AC"
    assert row["Regular price"] == 100.0
    assert row["Sale price"] == 90.0
    assert row["Meta: _woodmart_product_custom_tab_content"] == "<table></table>"

def test_unknown_dimensions_are_blank_not_zero():
    """A fabricated 0.0 would set wrong physical dimensions on the live product."""
    from app.models.dimensions import DimensionsResult

    raw_input = RawProductInput(
        sku="S1", model_number="M1", brand_name="Haier", category_name="AC",
        product_type="Air Conditioner", regular_price=Decimal(100), sale_price=Decimal(90),
    )
    # weight found (0.5), dimensions unknown (0.0) -> weight kept, dims blank.
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(), raw_input=raw_input,
        name="Haier M1 AC", short_description="<p>x</p>", description="d",
        specs_table_html="<table></table>", resolved_warranty_phrase="1-Year",
        dimensions=DimensionsResult(weight_kg=0.5, length_cm=0.0, width_cm=0.0, height_cm=0.0),
    )
    row = assemble_csv_row(state, "Electronics > AC", "Haier", canonical_category_path="Electronics > AC")
    assert row["Weight (kg)"] == 0.5
    assert row["Length (cm)"] == ""
    assert row["Width (cm)"] == ""
    assert row["Height (cm)"] == ""

def test_assemble_csv_row_passthrough_overlay():
    raw_input = RawProductInput(
        sku="S1", model_number="M1", brand_name="Haier", category_name="AC",
        product_type="Air Conditioner", regular_price=Decimal(100), sale_price=Decimal(90),
        passthrough_columns={
            "IMAGES": "http://example.com/img1.jpg, http://example.com/img2.jpg",
            "sale price": "85.0",  # Test case-insensitive overwrite
            "Length (cm)": " ",     # Test blank skip
            "Unknown Col": "foo"   # Test ignoring unknown
        }
    )
    
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(), raw_input=raw_input,
        name="Haier M1 AC", short_description="x", description="d",
        specs_table_html="<table></table>", resolved_warranty_phrase="1-Year",
    )
    
    row = assemble_csv_row(state, "Electronics > AC", "Haier", canonical_category_path="Electronics > AC")
    
    # Overwritten by passthrough
    assert row["Images"] == "http://example.com/img1.jpg, http://example.com/img2.jpg"
    assert row["Sale price"] == "85.0"
    
    # Not overwritten because value was blank (" ")
    assert row["Length (cm)"] == ""
    
    # Not present in COLUMN_ORDER
    assert "Dimensions" not in row
    assert "Unknown Col" not in row


def test_generate_csv_quoting():
    rows = [
        {col: "" for col in COLUMN_ORDER}
    ]
    rows[0]["SKU"] = "S1"
    rows[0]["Name"] = 'Product with "quotes" and , commas'
    
    content = generate_csv_file(rows)
    assert '"S1"' in content
    assert '"Product with ""quotes"" and , commas"' in content

def test_assemble_csv_row_strips_newlines_and_tabs():
    raw_input = RawProductInput(
        sku="S1", model_number="M1", brand_name="Haier", category_name="AC",
        product_type="Air Conditioner", regular_price=Decimal(100), sale_price=Decimal(90),
    )
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(), raw_input=raw_input,
        name="Name\r\nWith\nNewlines", 
        short_description="<p>\tTabbed</p>\n", 
        description="Full\rDesc",
        specs_table_html="<table>\n<tr>\t<td></td>\n</tr>\n</table>", 
        resolved_warranty_phrase="1-Year"
    )
    row = assemble_csv_row(state, "Electronics > AC", "Haier", canonical_category_path="Electronics > AC")
    
    assert "\n" not in row["Name"]
    assert "\r" not in row["Name"]
    assert "\n" not in row["Short description"]
    assert "\t" not in row["Short description"]
    assert "\r" not in row["Description"]
    assert "\n" not in row["Meta: _woodmart_product_custom_tab_content"]
    assert "\t" not in row["Meta: _woodmart_product_custom_tab_content"]

def test_assemble_csv_row_manual_chopper_alias():
    raw_input = RawProductInput(
        sku="S1", model_number="M1", brand_name="Anex", category_name="Manual Chopper",
        product_type="Chopper", regular_price=Decimal(100), sale_price=Decimal(90),
    )
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(), raw_input=raw_input,
        name="Name", short_description="x", description="d",
        specs_table_html="t", resolved_warranty_phrase="1-Year"
    )
    row = assemble_csv_row(state, "Kitchen Appliances > Manual Chopper", "Anex", canonical_category_path="Kitchen Appliances > Manual Chopper")
    
    assert row["Categories"] == "Kitchen Appliances > Chopper"
