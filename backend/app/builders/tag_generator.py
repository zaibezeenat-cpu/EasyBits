def build_tags(brand: str, category: str) -> str:
    """
    Builds exactly 3 tags: [Brand], [Category], HW
    """
    tags = [brand, category, "HW"]
    return ", ".join(tags)
