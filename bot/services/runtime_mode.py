"""Runtime feature gates for staging and migration modes."""

from __future__ import annotations

import os


def env_flag(name: str, default: bool = False) -> bool:
    """Read a conventional boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def saas_client_mode_enabled() -> bool:
    """Return True when SaaS owns commercial and access state."""
    return env_flag("WAVEMESH_SAAS_CLIENT_MODE", default=False)


def legacy_commercial_writes_enabled() -> bool:
    """Allow legacy local orders, trial activation and payment mutations."""
    if saas_client_mode_enabled():
        return False
    return env_flag("WAVEMESH_LEGACY_COMMERCIAL_WRITES_ENABLED", default=True)


def legacy_xui_writes_enabled() -> bool:
    """Allow direct legacy mutations against 3x-ui."""
    if saas_client_mode_enabled():
        return False
    return env_flag("WAVEMESH_LEGACY_XUI_WRITES_ENABLED", default=True)
