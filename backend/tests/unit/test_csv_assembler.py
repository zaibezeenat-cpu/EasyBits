from app.builders.csv_assembler import assemble_csv_row, generate_csv_file, COLUMN_ORDER
from app.graph.state import PipelineState
from app.models.raw_input import RawProductInput
from uuid import uuid4
from decimal import Decimal

def test_assemble_csv_row_columns():
    raw_input = RawProductInput(
        sku="TEST-SKU-1",
        model_number="MODEL-123",
        brand_name="Haier",
        category_name="AC",
        product_type="Air Conditioner",
        regular_price=Decimal("100"),
        sale_price=Decimal("90")
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
        product_type="Air Conditioner", regular_price=Decimal("100"), sale_price=Decimal("90"),
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


def test_generate_csv_quoting():
    rows = [
        {col: "" for col in COLUMN_ORDER}
    ]
    rows[0]["SKU"] = "S1"
    rows[0]["Name"] = 'Product with "quotes" and , commas'
    
    content = generate_csv_file(rows)
    assert '"S1"' in content
    assert '"Product with ""quotes"" and , commas"' in content
