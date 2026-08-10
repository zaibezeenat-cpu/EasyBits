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


def test_owner_reported_anex_ag01_features_value_is_readable():
    """
    The exact real-world case (Anex AG-01, owner-reported): a scraped bullet
    list flattened to one string with no spacing at all -- a garbled run-on
    that must render as normal, readable text without altering any word.
    """
    c_id = uuid4()
    schema = CategorySpecSchema(
        id=uuid4(), category_id=c_id,
        fields=[SpecField(key="features", label="Features")],
        created_at=datetime.now(), updated_at=datetime.now(),
    )
    raw = (
        "Easy to use.Manual Food Cutter.Easy to use string-operated chopper."
        "Quickly chops your vegetables and fruits.onion, tomato,"
    )
    extraction = ExtractionResult(
        product_id="p1", category_key="chopper",
        citations=[SourceCitation(field_name="features", value=raw, source_type="official",
                                   confidence="confirmed", fetched_at=datetime.now())],
    )

    html = render_specs_table(extraction, schema, "2 Year Official Brand Warranty")

    assert ".Manual" not in html, "period must not run straight into the next word"
    assert "Manual. Manual" not in html
    assert "tomato,</td>" not in html, "a dangling trailing comma must not reach the table"
    assert "onion, tomato</td>" in html
    assert "Easy to use. Manual Food Cutter. Easy to use string-operated chopper. " \
           "Quickly chops your vegetables and fruits. onion, tomato" in html


def test_decimal_spec_values_are_never_touched():
    """
    THE REGRESSION GUARD: the naive fix ("insert a space after every period")
    would turn a real decimal capacity like "9.5L" into "9. 5L" -- a visibly
    wrong number. Digit-period-digit must survive untouched.
    """
    c_id = uuid4()
    schema = CategorySpecSchema(
        id=uuid4(), category_id=c_id,
        fields=[SpecField(key="cap", label="Capacity"), SpecField(key="voltage", label="Voltage")],
        created_at=datetime.now(), updated_at=datetime.now(),
    )
    extraction = ExtractionResult(
        product_id="p1", category_key="fridge",
        citations=[
            SourceCitation(field_name="cap", value="9.5 Cu Ft", source_type="official",
                            confidence="confirmed", fetched_at=datetime.now()),
            SourceCitation(field_name="voltage", value="3.7V", source_type="official",
                            confidence="confirmed", fetched_at=datetime.now()),
        ],
    )

    html = render_specs_table(extraction, schema, "1 Year Warranty")

    assert "9.5 Cu Ft" in html
    assert "9. 5" not in html
    assert "3.7V" in html
    assert "3. 7" not in html


def test_tidy_spec_value_directly():
    from app.builders.specs_renderer import _tidy_spec_value

    assert _tidy_spec_value("A.B") == "A. B"
    assert _tidy_spec_value("9.5") == "9.5"
    assert _tidy_spec_value("220V,50Hz") == "220V, 50Hz"
    assert _tidy_spec_value("onion, tomato,") == "onion, tomato"
    assert _tidy_spec_value("Stainless Steel") == "Stainless Steel"
