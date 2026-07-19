"""Pure callback contracts and priority overrides for guided onboarding."""
from __future__ import annotations

from typing import Optional


HAPP_DISTRIBUTIONS = {
    "ios": {"ru", "global"},
    "android": {"google_play"},
    "windows": {"windows"},
    "macos": {"macos"},
}


def parse_happ_callback(data: str) -> Optional[tuple[str, str, int]]:
    """Parse platform callbacks and legacy iOS region callbacks."""
    parts = data.split(":")
    if len(parts) == 3:
        _, distribution, raw_key_id = parts
        platform = "ios"
    elif len(parts) == 4:
        _, platform, distribution, raw_key_id = parts
    else:
        return None

    if distribution not in HAPP_DISTRIBUTIONS.get(platform, set()):
        return None
    try:
        key_id = int(raw_key_id)
    except (TypeError, ValueError):
        return None
    return platform, distribution, key_id


def _key_id(ctx: dict) -> Optional[str]:
    value = ctx.get("key_id")
    if value is None or value == "":
        return None
    return str(value)


def _back_from_happ_primary(ctx: dict) -> Optional[dict]:
    """HAPP is primary, so Back returns to device selection."""
    key_id = _key_id(ctx)
    return {"callback_data": f"onboarding_ready:{key_id}"} if key_id else None


def _back_to_happ_region(ctx: dict) -> Optional[dict]:
    """Return from an iOS HAPP distribution page to region selection."""
    key_id = _key_id(ctx)
    return {"callback_data": f"onboarding_platform:ios:{key_id}"} if key_id else None


def install_priority_overrides() -> None:
    """Adapt legacy onboarding button contracts to HAPP-first navigation."""
    from bot.utils.action_registry import SYSTEM_BUTTONS

    SYSTEM_BUTTONS["btn_onboarding_happ_back_primary"] = _back_from_happ_primary
    SYSTEM_BUTTONS["btn_onboarding_happ_back_region"] = _back_to_happ_region


install_priority_overrides()
