"""QR/link delivery used inside the guided onboarding wizard."""
from __future__ import annotations

import logging
from typing import Optional

from aiogram.types import BufferedInputFile, CallbackQuery

from bot.utils.key_generator import generate_link, generate_qr_code
from bot.utils.key_sender_core import format_key_copy_value
from bot.utils.placeholders import apply_placeholder_replacements

logger = logging.getLogger(__name__)


async def _access_value(key: dict) -> Optional[str]:
    from bot.services.runtime_mode import saas_client_mode_enabled
    if saas_client_mode_enabled():
        from bot.handlers.user.saas_keys import dashboard
        from bot.handlers.user.payments.payment_return import load_verified_ready_payment_return
        result = await dashboard(key["telegram_id"])
        matches = [a for a in result.get("accesses", []) if isinstance(a, dict)
                   and a.get("legacy_key_id") == str(key["id"]) and a.get("authority") == "managed"]
        if len(matches) != 1:
            return None
        verified = await load_verified_ready_payment_return(telegram_id=key["telegram_id"], access_id=matches[0]["access_id"])
        return verified.subscription_url
    from bot.services.vpn_api import (
        get_client,
        get_subscription_url_for_key,
        is_subscription_mode,
    )

    if key.get("sub_id") and is_subscription_mode():
        return await get_subscription_url_for_key(key)

    if not key.get("server_id") or not key.get("panel_email"):
        return None
    client = await get_client(int(key["server_id"]))
    config = await client.get_client_config(key["panel_email"])
    return generate_link(config) if config else None


async def send_onboarding_connection(
    callback: CallbackQuery,
    key: dict,
    *,
    page_key: str,
    fallback_text: str,
    context: dict,
) -> bool:
    """Render an editable onboarding caption together with the access QR code."""
    from bot.utils.message_editor import get_message_data
    from bot.utils.page_renderer import build_page_keyboard
    from bot.utils.text import safe_edit_or_send
    from bot.services.runtime_mode import saas_client_mode_enabled
    from bot.services.private_chat import private_actor_id

    if saas_client_mode_enabled() and (private_actor_id(callback) is None
            or key.get("telegram_id") != private_actor_id(callback)):
        return False

    try:
        raw_value = await _access_value(key)
    except Exception as exc:
        logger.warning(
            "Onboarding access value failed for key_id=%s error=%s",
            key.get("id"),
            type(exc).__name__,
        )
        raw_value = None

    if not raw_value:
        await safe_edit_or_send(
            callback.message,
            "❌ <b>Не удалось получить ссылку подключения</b>\n\n"
            "Повторите попытку позже или обратитесь в поддержку @wavemesh.",
        )
        return False

    if not saas_client_mode_enabled() and key.get("sub_id") and raw_value.startswith(("http://", "https://")):
        from bot.services.subscription_readiness import wait_for_subscription_ready

        ready = await wait_for_subscription_ready(
            raw_value,
            key_id=key.get("id"),
            server_id=key.get("server_id"),
        )
        if not ready:
            await safe_edit_or_send(
                callback.message,
                "⏳ <b>Подключение ещё подготавливается</b>\n\n"
                "Ключ сохранён. Подождите немного и повторите открытие этого шага.",
            )
            return False

    replacements = {"%ключ%": format_key_copy_value(raw_value)}
    base_text = get_message_data(page_key, fallback_text).get("text") or fallback_text
    caption = apply_placeholder_replacements(base_text, replacements)
    if len(caption) > 1024:
        caption = (
            "🔗 <b>Добавьте подключение</b>\n\n"
            f"{format_key_copy_value(raw_value)}\n\n"
            "Импортируйте ссылку из буфера обмена или отсканируйте QR-код."
        )

    photo = BufferedInputFile(generate_qr_code(raw_value), filename="subscription_qr.png")
    markup = build_page_keyboard(page_key, context=context)
    rendered_message = await safe_edit_or_send(
        callback.message,
        caption,
        reply_markup=markup,
        photo=photo,
    )

    try:
        from config import ADMIN_IDS
        from bot.services.page_context import remember_page_context

        if callback.from_user.id in ADMIN_IDS:
            remember_page_context(
                callback.from_user.id,
                page_key=page_key,
                message=rendered_message,
                context=context,
                text_replacements=replacements,
            )
    except Exception as exc:
        logger.warning("Could not remember onboarding connection for /yaa: %s", exc)

    return True
