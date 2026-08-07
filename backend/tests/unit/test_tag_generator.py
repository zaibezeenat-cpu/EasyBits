from app.builders.tag_generator import build_tags


def test_tag_generator():
    tags = build_tags("Dawlance", "Air Conditioner")
    assert tags == "Dawlance, Air Conditioner, HW"
    assert len(tags.split(", ")) == 3
