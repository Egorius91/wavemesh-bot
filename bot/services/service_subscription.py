"""Strict service URL/material validation; no network, local panel or billing."""
import base64
import re
from urllib.parse import parse_qsl, urlsplit

LOCATOR = r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}"
KEYS = {"access_id", "ready", "status", "desired_version", "material_version", "kind", "subscription_url"}


def _https(value):
    if (not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\x00-\x1f\x7f]", value)
            or re.search(r"%(?![0-9a-fA-F]{2})", value)):
        raise ValueError("Invalid service address")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment
                or url.port is not None and not 1 <= url.port <= 65535 or "\\" in value):
            raise ValueError()
        return url
    except (ValueError, TypeError):
        raise ValueError("Invalid service address") from None


def subscription_address(value):
    url = _https(value)
    match = re.fullmatch(r"/api/subscriptions/(" + LOCATOR + r")/(wvs1_([A-Za-z0-9_-]{43}))", url.path)
    if not match or url.query:
        raise ValueError("Invalid service subscription")
    encoded = match[3]
    decoded = base64.urlsafe_b64decode(encoded + "=")
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != encoded:
        raise ValueError("Invalid service subscription")
    return value


def service_material(value, access_id):
    if (not isinstance(access_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", access_id)
            or not isinstance(value, dict) or set(value) != KEYS or value.get("access_id") != access_id
            or value.get("ready") is not True or value.get("status") != "ready" or value.get("material_version") != 2
            or type(value.get("material_version")) is not int or value.get("kind") != "service_subscription"
            or type(value.get("desired_version")) is not int or not 1 <= value["desired_version"] <= 2147483647):
        raise ValueError("Invalid service material")
    subscription_address(value.get("subscription_url"))
    return value.copy()


def renewal_address(value, access_id):
    url = _https(value)
    try:
        query = parse_qsl(url.query, strict_parsing=True, max_num_fields=1, encoding="utf-8", errors="strict")
    except (ValueError, UnicodeError):
        raise ValueError("Invalid renewal address") from None
    if url.path != "/pricing" or query != [("accessId", access_id)]:
        raise ValueError("Invalid renewal address")
    return value
