"""Pure helpers for 3X-UI subscription delivery."""

from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urlsplit, urlunsplit

from bot.utils.inbounds import IGNORED_INBOUND_PREFIX


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled", ""}


def panel_bool(value: Any, default: bool = False) -> bool:
    """Normalize bool-like values returned by different 3X-UI versions."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return bool(value)


def is_public_subscription_inbound(inbound: Dict[str, Any]) -> bool:
    """Return whether an inbound may receive a client for a public subscription."""
    if not isinstance(inbound, dict):
        return False
    remark = str(inbound.get("remark") or "").lstrip()
    if remark.startswith(IGNORED_INBOUND_PREFIX):
        return False
    return panel_bool(inbound.get("enable"), default=True)


def filter_public_subscription_inbounds(
    inbounds: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep enabled, client-visible inbounds while preserving panel order."""
    return [inbound for inbound in inbounds if is_public_subscription_inbound(inbound)]


def _tls_enabled(settings: Dict[str, Any]) -> bool:
    return bool(
        str(settings.get("subCertFile") or "").strip()
        and str(settings.get("subKeyFile") or "").strip()
    )


def _domain_parts(value: Any, fallback_host: str, default_scheme: str) -> tuple[str, str]:
    raw = str(value or fallback_host or "").strip()
    if not raw:
        return default_scheme, ""

    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    scheme = parsed.scheme or default_scheme
    netloc = parsed.netloc or parsed.path.strip("/")
    return scheme, netloc


def _has_explicit_port(netloc: str) -> bool:
    try:
        return urlsplit(f"//{netloc}").port is not None
    except ValueError:
        return True


def _direct_origin(settings: Dict[str, Any], fallback_host: str) -> Optional[str]:
    default_scheme = "https" if _tls_enabled(settings) else "http"
    scheme, netloc = _domain_parts(settings.get("subDomain"), fallback_host, default_scheme)
    if not netloc:
        return None

    try:
        port = int(settings.get("subPort") or 0)
    except (TypeError, ValueError):
        port = 0
    default_port = 443 if scheme == "https" else 80
    if port and port != default_port and not _has_explicit_port(netloc):
        netloc = f"{netloc}:{port}"
    return f"{scheme}://{netloc}"


def _append_subscription_id(prefix: str, sub_id: str) -> Optional[str]:
    parsed = urlsplit(prefix)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    path += quote(str(sub_id), safe="")
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def build_public_subscription_url(
    settings: Dict[str, Any],
    sub_id: str,
    fallback_host: str = "",
) -> Optional[str]:
    """
    Build a public subscription URL from 3X-UI settings.

    ``subURI`` is authoritative. WaveMesh Node Builder publishes its opaque
    nginx URL there. Older panels without ``subURI`` keep working through the
    direct ``subDomain``/``subPort``/``subPath`` settings. No path name is
    guessed by the bot.
    """
    if not settings or not sub_id or not panel_bool(settings.get("subEnable"), default=False):
        return None

    origin = _direct_origin(settings, fallback_host)
    sub_uri = str(settings.get("subURI") or "").strip()
    if sub_uri:
        if "://" in sub_uri:
            prefix = sub_uri
        elif origin:
            prefix = f"{origin.rstrip('/')}/{sub_uri.lstrip('/')}"
        else:
            return None
        return _append_subscription_id(prefix, sub_id)

    if not origin:
        return None
    sub_path = str(settings.get("subPath") or "/").strip() or "/"
    prefix = f"{origin.rstrip('/')}/{sub_path.lstrip('/')}"
    return _append_subscription_id(prefix, sub_id)
