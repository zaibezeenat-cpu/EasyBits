from datetime import datetime

from app.builders.dimensions_builder import build_dimensions
from app.models.extraction import ExtractionResult, SourceCitation


def test_dimensions_builder_net_to_gross_shipping():
    citation_weight = SourceCitation(
        field_name="weight_kg", value="15.5 kg", source_url="http://x.com",
        source_type="official", confidence="confirmed", fetched_at=datetime.now()
    )
    citation_length = SourceCitation(
        field_name="length_cm", value="UNKNOWN", source_url=None,
        source_type="official", confidence="unreachable", fetched_at=datetime.now()
    )
    
    extraction = ExtractionResult(
        product_id="p1", category_key="ac",
        citations=[citation_weight, citation_length]
    )
    
    dims = build_dimensions(extraction)
    # Net 15.5 kg converts to shipping gross weight (15.5 * 1.10 + 0.10 = 17.15 kg)
    assert dims.weight_kg == 17.15
    assert dims.length_cm == 0.0
    assert dims.width_cm == 0.0
    assert dims.height_cm == 0.0

def test_dimensions_builder_explicit_shipping_gross():
    citation_shipping_weight = SourceCitation(
        field_name="shipping_gross_weight_kg", value="18.0 kg", source_url="http://x.com",
        source_type="official", confidence="confirmed", fetched_at=datetime.now()
    )
    citation_shipping_length = SourceCitation(
        field_name="shipping_length_cm", value="55.0 cm", source_url="http://x.com",
        source_type="official", confidence="confirmed", fetched_at=datetime.now()
    )
    
    extraction = ExtractionResult(
        product_id="p2", category_key="beauty",
        citations=[citation_shipping_weight, citation_shipping_length]
    )
    
    dims = build_dimensions(extraction)
    assert dims.weight_kg == 18.0
    assert dims.length_cm == 55.0
    assert dims.width_cm == 0.0
    assert dims.height_cm == 0.0
