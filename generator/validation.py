"""Input rules for the QR API.

A link must be an absolute http(s) URL with a host. Intranet links such as ``http://fileserver/share/a.mp4`` are
allowed on purpose: the tool was made for an office network, where file servers often have no public domain name.
"""
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# A file link from a cloud drive or an intranet server is far shorter than this. Longer content still fits in a QR
# code, but the symbol gets so dense that a phone struggles to read it off a printed sheet.
MAX_URL_LENGTH = 1024

ALLOWED_SCHEMES = ("http", "https")
FORMATS = ("png", "svg")
ERROR_LEVELS = ("L", "M", "Q", "H")
DEFAULT_ERROR_LEVEL = "M"
DEFAULT_SCALE = 10
MIN_SCALE, MAX_SCALE = 1, 40

_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
_HAS_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


class ValidationError(Exception):
    """A request the API refuses, with a stable machine-readable code."""

    def __init__(self, code, message, field=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


@dataclass(frozen=True)
class QRRequest:
    url: str
    format: str
    error: str
    scale: int


def _valid_host(host):
    if not host:
        return False
    if host.startswith("[") and host.endswith("]"):
        try:
            ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return False
        return True
    try:
        ipaddress.IPv4Address(host)
        return True
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode("ascii")  # internationalized domain names are allowed
    except UnicodeError:
        return False
    if len(ascii_host) > 253:
        return False
    return all(_HOST_LABEL.match(label) for label in ascii_host.rstrip(".").split("."))


def validate_url(value):
    """Return the link trimmed of surrounding whitespace, or raise ValidationError."""
    if value is None:
        raise ValidationError("missing_url", "Field 'url' is required.", "url")
    if not isinstance(value, str):
        raise ValidationError("invalid_url", "Field 'url' must be a string.", "url")
    url = value.strip()
    if not url:
        raise ValidationError("missing_url", "Field 'url' must not be empty.", "url")
    if len(url) > MAX_URL_LENGTH:
        raise ValidationError(
            "url_too_long", f"The link is {len(url)} characters; the limit is {MAX_URL_LENGTH}.", "url"
        )
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValidationError("invalid_url", "The link must not contain spaces or control characters.", "url")
    match = _HAS_SCHEME.match(url)
    # "example.com/a" and "example.com:8080/a" have no scheme, though the second looks like one to a URL parser.
    if not match or "." in match.group(0) or url[match.end():match.end() + 1].isdigit():
        raise ValidationError("missing_scheme", "The link must start with http:// or https://.", "url")

    try:
        parts = urlsplit(url)
    except ValueError:  # e.g. a bracketed host that is not an IPv6 address
        raise ValidationError("invalid_url", "The link has no valid host name.", "url") from None
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValidationError(
            "unsupported_scheme", f"Only http and https links are accepted, not '{parts.scheme}:'.", "url"
        )
    if not url[len(parts.scheme) + 1:].startswith("//"):
        raise ValidationError("invalid_url", "The link has no host.", "url")
    try:
        port = parts.port  # raises ValueError for a port outside 0-65535 or one that is not a number
        host = parts.hostname or ""
        if parts.netloc.rsplit("@", 1)[-1].startswith("["):
            host = f"[{host}]"
    except ValueError:
        raise ValidationError("invalid_url", "The link has an invalid port.", "url") from None
    if port == 0 or not _valid_host(host):
        raise ValidationError("invalid_url", "The link has no valid host name.", "url")
    if parts.username is not None or parts.password is not None:
        # A QR code is printed and handed out; a password inside the link would go with it.
        raise ValidationError("credentials_in_url", "The link must not contain a user name or password.", "url")
    return url


def parse_request(data):
    """Validate the decoded JSON body of POST /api/qr."""
    if not isinstance(data, dict):
        raise ValidationError("invalid_body", "The request body must be a JSON object.")

    url = validate_url(data.get("url"))

    fmt = data.get("format", "png")
    if not isinstance(fmt, str) or fmt.lower() not in FORMATS:
        raise ValidationError("invalid_option", f"Field 'format' must be one of: {', '.join(FORMATS)}.", "format")

    error = data.get("error_correction", DEFAULT_ERROR_LEVEL)
    if not isinstance(error, str) or error.upper() not in ERROR_LEVELS:
        raise ValidationError(
            "invalid_option", f"Field 'error_correction' must be one of: {', '.join(ERROR_LEVELS)}.",
            "error_correction",
        )

    scale = data.get("scale", DEFAULT_SCALE)
    if isinstance(scale, bool) or not isinstance(scale, int) or not MIN_SCALE <= scale <= MAX_SCALE:
        raise ValidationError(
            "invalid_option", f"Field 'scale' must be an integer from {MIN_SCALE} to {MAX_SCALE}.", "scale"
        )

    return QRRequest(url=url, format=fmt.lower(), error=error.upper(), scale=scale)
