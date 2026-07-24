"""Onboarding-aware facade for the standard VPN key sender."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot.services.access_shadow import schedule_key_access_shadow_sync

from . import key_sender_core as _core
from .key_card_onboarding import (
    KEY_CARD_CONTEXT_KEY_ID,
    add_onboarding_button,
    rerender_subscription_key_card,
    send_subscription_key_card,
)
from .key_sender_core import *  # noqa: F401,F403

send_key_with_qr_raw = _core.send_key_with_qr


async def send_key_with_qr(
    messageable,
    key_data: dict,
    key_manage_markup: InlineKeyboardMarkup = None,
    is_new: bool = False,
):
    """Start onboarding for new keys and expose it on existing key cards."""
    key_id = key_data.get("id")
    if key_id is not None:
        schedule_key_access_shadow_sync(
            int(key_id),
            reason="key_delivery_new" if is_new else "key_delivery_existing",
        )

    if is_new:
        from bot.handlers.user.onboarding import start_key_onboarding

        return await start_key_onboarding(messageable, key_data)

    from bot.services.vpn_api import is_subscription_mode

    if key_data.get("sub_id") and is_subscription_mode():
        return await send_subscription_key_card(
            messageable,
            key_data,
            fallback_markup=key_manage_markup,
        )

    return await _core.send_key_with_qr(
        messageable,
        key_data,
        key_manage_markup=add_onboarding_button(
            key_manage_markup,
            key_id,
        ),
        is_new=False,
    )


async def rerender_key_delivery_page_context(page_context, viewer_id: int) -> bool:
    """Preserve the selected-key onboarding button after /yaa edits."""
    context = page_context.context or {}
    if context.get(KEY_CARD_CONTEXT_KEY_ID) is not None:
        return await rerender_subscription_key_card(page_context, viewer_id)
    return await _core.rerender_key_delivery_page_context(page_context, viewer_id)
