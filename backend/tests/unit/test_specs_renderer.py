from datetime import datetime
from uuid import uuid4

from app.builders.specs_renderer import render_specs_table
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.taxonomy import CategorySpecSchema, SpecField


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

def test_render_specs_table_skips_empty_unknown():
    c_id = uuid4()
    schema = CategorySpecSchema(
        id=uuid4(), category_id=c_id, 
        fields=[
            SpecField(key="cap", label="Capacity"),
            SpecField(key="color", label="Color"),
            SpecField(key="weight", label="Weight"),
            SpecField(key="material", label="Material")
        ],
        created_at=datetime.now(), updated_at=datetime.now()
    )
    extraction = ExtractionResult(
        product_id="p1", category_key="microwave",
        citations=[
            SourceCitation(field_name="cap", value="20L", source_type="official", confidence="confirmed", fetched_at=datetime.now()),
            SourceCitation(field_name="color", value="UNKNOWN", source_type="official", confidence="unreachable", fetched_at=datetime.now()),
            SourceCitation(field_name="weight", value="", source_type="official", confidence="unreachable", fetched_at=datetime.now()),
            SourceCitation(field_name="material", value="Not Available", source_type="official", confidence="unreachable", fetched_at=datetime.now())
        ]
    )
    
    html = render_specs_table(extraction, schema, "1-Year Warranty")
    
    # Valid field should be present
    assert "Capacity" in html
    assert "20L" in html
    
    # Invalid/Empty fields should be entirely skipped
    assert "Color" not in html
    assert "UNKNOWN" not in html.upper()
    
    assert "Weight" not in html
    
    assert "Material" not in html
    assert "NOT AVAILABLE" not in html.upper()
