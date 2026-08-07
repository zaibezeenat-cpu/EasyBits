from app.models.writer_output import WriterOutput


def render_short_description(writer_output: WriterOutput, product_name: str, category_name: str, warranty_phrase: str) -> str:
    """
    Renders the short description HTML (Phase 1 §7.2).
    """
    # Category hooks (could be moved to a DB or config later)
    hooks = {
        "Microwave Oven": "Experience the convenience of",
        "Washing Machine": "Simplify your laundry with",
        "Air Conditioner": "Stay cool and comfortable with",
        "Refrigerator": "Keep your food fresh with",
        "Inverter": "Ensure uninterrupted power with"
    }
    hook = hooks.get(category_name, "Discover the excellence of")
    
    f1 = writer_output.short_desc_feature_1 or "advanced technology"
    f2 = writer_output.short_desc_feature_2 or "efficient performance"
    f3 = writer_output.short_desc_feature_3 or "elegant design"
    
    # Template: <p>[CATEGORY_HOOK] the <strong>{{PRODUCT_NAME}}</strong>. 
    # Designed for modern homes, this premium appliance features {{FEATURE_1}}, {{FEATURE_2}}, and {{FEATURE_3}}. 
    # With [extra_feature], it ensures effortless and secure operation. Backed by a {{WARRANTY}}.</p>
    
    html = f"<p>{hook} the <strong>{product_name}</strong>. "
    html += f"Designed for modern homes, this premium appliance features {f1}, {f2}, and {f3}. "
    html += "With its smart design, it ensures effortless and secure operation. "
    html += f"Backed by a {warranty_phrase}.</p>"
    
    return html
