from app.builders.specs_renderer import render_specs_table
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.taxonomy import CategorySpecSchema, SpecField
from datetime import datetime
from uuid import uuid4

def test_render_specs_table_basic():
    c_id = uuid4()
    schema = CategorySpecSchema(
        id=uuid4(), category_id=c_id, 
        fields=[SpecField(key="cap", label="Capacity")],
        created_at=datetime.now(), updated_at=datetime.now()
    )
    extraction = ExtractionResult(
        product_id="p1", category_key="microwave",
        citations=[SourceCitation(field_name="cap", value="20L", source_type="official", confidence="confirmed", fetched_at=datetime.now())]
    )
    
    html = render_specs_table(extraction, schema, "1-Year Warranty")
    assert "<table class='shop_attributes'" in html
    assert "<thead>" in html
    assert "SPECIFICATION" in html
    assert "DETAILS" in html
    assert "Capacity" in html
    assert "20L" in html
    assert "Warranty" in html
    assert "bold" in html.lower()
