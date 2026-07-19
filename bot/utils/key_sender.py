"""Onboarding-aware facade for VPN key delivery.

The implementation lives in ``key_sender_core``. Newly issued keys enter the
guided setup wizard; existing-key and technical delivery calls keep the normal
QR/config behavior.
"""
from __future__ import annotations

from typing import Optional

from aiogram.types import InlineKeyboardMarkup

from . import key_sender_core as _core
from .key_sender_core import *  # noqa: F401,F403

send_key_with_qr_raw = _core.send_key_with_qr


async def send_key_with_qr(
    messageable,
    key_data: dict,
    key_manage_markup: InlineKeyboardMarkup = None,
    is_new: bool = False,
    page_key: str = _core.KEY_DELIVERY_PAGE,
    fallback_text: str = _core.DEFAULT_KEY_DELIVERY_TEXT,
    use_page_markup: bool = True,
    onboarding_platform: Optional[str] = None,
    onboarding_app: Optional[str] = None,
    onboarding_region: Optional[str] = None,
    onboarding_distribution: Optional[str] = None,
):
    """Start guided onboarding for a newly issued key, otherwise deliver it."""
    should_start_onboarding = (
        is_new
        and page_key == _core.KEY_DELIVERY_PAGE
        and not onboarding_platform
        and not onboarding_app
    )
    if should_start_onboarding:
        from bot.handlers.user.onboarding import start_key_onboarding

        return await start_key_onboarding(messageable, key_data)

    return await _core.send_key_with_qr(
        messageable,
        key_data,
        key_manage_markup=key_manage_markup,
        is_new=is_new,
        page_key=page_key,
        fallback_text=fallback_text,
        use_page_markup=use_page_markup,
        onboarding_platform=onboarding_platform,
        onboarding_app=onboarding_app,
        onboarding_region=onboarding_region,
        onboarding_distribution=onboarding_distribution,
    )
