"""
Normalises and validates the domains the operator types into Settings.

WHY THIS EXISTS
---------------
Source discovery matches a scraped URL's host against the stored value. It does
a host comparison, not a URL comparison -- so a stored "https://kenwood.com.pk/"
never matches the host "kenwood.com.pk", and the brand's own site is silently
skipped. The failure is invisible: discovery simply reports no official source
and the product escalates to Manual Review, looking like a product with no data
rather than a mistyped setting.

Pasting a full URL is the *expected* operator behaviour -- the brand list the
owner supplied is a list of URLs. So this normalises rather than rejects, and
only refuses input that could not be a domain at all.
"""
import re
from urllib.parse import urlparse

# Deliberately permissive on TLD length: ".com.pk" and newer long TLDs must pass.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)

MAX_DOMAIN_LENGTH = 253


class InvalidDomainError(ValueError):
    """Raised when a value cannot be reduced to a usable hostname."""


# A path is kept, but only as a scope prefix -- never a query, fragment, or an
# obviously non-navigational suffix.
_MAX_PATH_LENGTH = 120


def normalize_domain(raw: str) -> str:
    """
    Reduces operator input to `host` or `host/path`.

        "https://www.kenwood.com.pk/"          -> "kenwood.com.pk"
        "  Dawlance.com  "                     -> "dawlance.com"
        "https://dwphome.pk/ecostar"           -> "dwphome.pk/ecostar"
        "https://www.haier.com/pk/"            -> "haier.com/pk"

    WHY THE PATH IS KEPT (and why an earlier version of this function was wrong
    to discard it): one host can be the official source for several brands. DWP
    Home distributes both EcoStar and Gree at dwphome.pk/ecostar and
    dwphome.pk/gree, and Haier's official Pakistan site is a subdirectory of its
    global site. Reducing those to a bare host makes two brands identical and
    silently swaps a regional site for a global one -- see `SourceScope` in
    `app/scraping/source_discovery.py`, which consumes this value.

    Query strings and fragments ARE dropped: they are tracking or in-page
    anchors, never part of a source's identity.

    Strips `www.` because the scraped host may or may not carry it; storing the
    bare form means both variants match.

    Raises `InvalidDomainError` rather than storing a best guess: a stored
    non-domain disables discovery for that brand without any visible symptom,
    so failing at the point of entry -- where the operator can fix it -- is the
    only place the error is actually actionable.
    """
    if not raw or not raw.strip():
        raise InvalidDomainError("Domain cannot be empty.")

    value = raw.strip().lower()

    # A scheme means it is a URL; let urlparse split it rather than
    # string-slicing, which gets ports and credentials wrong.
    if "://" in value:
        parsed = urlparse(value)
        host, path = (parsed.netloc or parsed.path), parsed.path if parsed.netloc else ""
    else:
        host, _, rest = value.partition("/")
        path = f"/{rest}" if rest else ""

    # Drop credentials and port from the host.
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]

    # Tracking params and anchors are not part of a source's identity.
    path = path.split("?")[0].split("#")[0].rstrip("/")

    if len(host) > MAX_DOMAIN_LENGTH:
        raise InvalidDomainError(f"Domain is longer than {MAX_DOMAIN_LENGTH} characters.")

    if not _DOMAIN_RE.match(host):
        raise InvalidDomainError(
            f"'{raw.strip()[:60]}' is not a valid domain. "
            "Enter it like 'kenwood.com.pk' or paste the brand's homepage URL."
        )

    if len(path) > _MAX_PATH_LENGTH:
        raise InvalidDomainError(
            f"The path after the domain is longer than {_MAX_PATH_LENGTH} characters. "
            "Enter the brand's section URL, not a link to one product."
        )

    return f"{host}{path}"
