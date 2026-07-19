"""Onboarding-aware facade for the standard VPN key sender."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from . import key_sender_core as _core
from .key_sender_core import *  # noqa: F401,F403

send_key_with_qr_raw = _core.send_key_with_qr


async def send_key_with_qr(
    messageable,
    key_data: dict,
    key_manage_markup: InlineKeyboardMarkup = None,
    is_new: bool = False,
):
    """Start guided setup for new keys; preserve normal delivery otherwise."""
    if is_new:
        from bot.handlers.user.onboarding import start_key_onboarding

        return await start_key_onboarding(messageable, key_data)
    return await _core.send_key_with_qr(
        messageable,
        key_data,
        key_manage_markup=key_manage_markup,
        is_new=False,
    )
