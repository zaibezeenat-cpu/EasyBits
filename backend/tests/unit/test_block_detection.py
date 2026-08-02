"""
Block-page detection: a Cloudflare / anti-bot challenge loads successfully and
returns HTML, but it is NOT the product. Without detecting it, the orchestrator
discards it as "product not listed" -- so the operator is told the wrong thing.
Detecting it lets the pipeline say "this site blocked us; paste the Details"
instead, which is the actionable truth.
"""
import pytest

from app.scraping.playwright_client import is_block_page


@pytest.mark.parametrize("content", [
    "Just a moment...\nEnable JavaScript and cookies to continue",
    "Checking your browser before accessing westpoint.pk",
    "Attention Required! | Cloudflare\nPlease enable cookies.",
    "Verify you are human by completing the action below.",
    "Access denied\nYou do not have permission to access this resource.",
    "Please turn JavaScript on and reload the page. DDoS protection by Cloudflare",
])
def test_known_block_pages_are_detected(content):
    assert is_block_page(content) is True


@pytest.mark.parametrize("content", [
    "Deluxe Hair Straightener WF-6807 35 Watts 2 Years Warranty Ceramic Coating Plate",
    "Haier HRF-246 EPR 10 Cu Ft Refrigerator Inverter Black Glass Door",
    "",
])
def test_real_product_pages_are_not_flagged(content):
    assert is_block_page(content) is False
