import re

from app.models.dimensions import DimensionsResult
from app.models.extraction import ExtractionResult


def build_dimensions(extraction: ExtractionResult) -> DimensionsResult:
    """
    Maps shipping gross weight and shipping box dimensions (LxWxH) to WooCommerce CSV columns 19-22.
    
    WooCommerce shipping columns require:
      - Weight (kg): Gross shipping weight (product + box packaging). Prioritizes explicit
        shipping/gross fields (shipping_gross_weight_kg, gross_weight_kg, package_weight_kg).
        If only net weight_kg is available, applies standard packaging allowance (+10% + 0.1 kg).
      - Length/Width/Height (cm): Outer shipping box dimensions for courier volume calculations.
        Prioritizes explicit shipping dimensions (shipping_length_cm, package_length_cm, etc.).
        If net product dimensions are given, adds +2 cm packaging box margin.
    """
    def _numeric_or_none(field_name: str) -> float | None:
        value = extraction.confirmed_value(field_name)
        if value is None or value == "UNKNOWN":
            return None
        match = re.search(r"[\d.]+", value)
        return float(match.group()) if match else None

    # --- Weight Calculation (Shipping Gross Weight) ---
    gross_weight = None
    for field in ("shipping_gross_weight_kg", "gross_weight_kg", "shipping_weight_kg", "package_weight_kg"):
        gross_weight = _numeric_or_none(field)
        if gross_weight is not None:
            break

    if gross_weight is None:
        net_weight = _numeric_or_none("weight_kg")
        if net_weight is not None and net_weight > 0:
            # Net to Gross conversion: add 10% packaging weight + 0.1 kg box allowance
            gross_weight = round(net_weight * 1.10 + 0.10, 2)

    # --- Dimensions Calculation (Shipping Box LxWxH) ---
    def _get_shipping_dim(shipping_field: str, net_field: str) -> float:
        ship_val = _numeric_or_none(shipping_field)
        if ship_val is not None:
            return round(ship_val, 1)
        net_val = _numeric_or_none(net_field)
        if net_val is not None and net_val > 0:
            # Net to Outer Box: add 2 cm box padding for shipping packaging
            return round(net_val + 2.0, 1)
        return 0.0

    return DimensionsResult(
        weight_kg=gross_weight if gross_weight is not None else 0.0,
        length_cm=_get_shipping_dim("shipping_length_cm", "length_cm"),
        width_cm=_get_shipping_dim("shipping_width_cm", "width_cm"),
        height_cm=_get_shipping_dim("shipping_height_cm", "height_cm"),
    )
