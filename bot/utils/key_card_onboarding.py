"""Onboarding-aware rendering for an existing VPN key card."""
from __future__ import annotations

import logging
from typing import Optional

from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.utils.key_generator import generate_qr_code
from bot.utils.key_sender_core import (
    KEY_DELIVERY_CONTEXT_ATTACH_MARKUP,
    KEY_DELIVERY_CONTEXT_IS_NEW,
    KEY_DELIVERY_CONTEXT_KIND,
    KEY_DELIVERY_CONTEXT_RAW,
    KEY_DELIVERY_PAGE,
    build_key_delivery_replacements,
    build_key_delivery_text,
    format_key_copy_value,
)

logger = logging.getLogger(__name__)

KEY_CARD_CONTEXT_KEY_ID = "key_delivery_key_id"

KEY_CARD_TEXT = (
    "🔐 <b>Данные подключения</b>\n\n"
    "Для пошаговой настройки нажмите кнопку <b>«🧭 Настроить VPN»</b>.\n\n"
    "Для ручного импорта используйте техническую ссылку или QR-код:\n"
    "%ключ%"
)

LEGACY_KEY_CARD_MARKERS = (
    "📱 <b>Инструкция:</b>",
    "Импортируйте в свой клиент",
    "Какой именно клиент подходит",
)


def normalize_key_card_template(template: str | None) -> str:
    """Replace only the known legacy key-card instructions."""
    value = template or KEY_CARD_TEXT
    if any(marker in value for marker in LEGACY_KEY_CARD_MARKERS):
        return KEY_CARD_TEXT
    return value


def build_key_card_caption(template: str | None, raw_value: str) -> str:
    """Build a Telegram-safe caption for a subscription URL."""
    caption = build_key_delivery_text(normalize_key_card_template(template), raw_value)
    if len(caption) <= 1024:
        return caption

    compact = (
        "🔐 <b>Данные подключения</b>\n\n"
        "Нажмите <b>«🧭 Настроить VPN»</b> для пошаговой настройки.\n\n"
        f"{format_key_copy_value(raw_value)}"
    )
    if len(compact) <= 1024:
        return compact

    return (
        "🔐 <b>Данные подключения</b>\n\n"
        "Нажмите <b>«🧭 Настроить VPN»</b> или отсканируйте QR-код."
    )


def add_onboarding_button(
    markup: Optional[InlineKeyboardMarkup],
    key_id: int | str | None,
) -> Optional[InlineKeyboardMarkup]:
    """Prepend a setup button bound to the selected key."""
    if key_id is None or key_id == "":
        return markup

    callback_data = f"onboarding_ready:{key_id}"
    rows = [list(row) for row in (markup.inline_keyboard if markup else [])]
    if any(button.callback_data == callback_data for row in rows for button in row):
        return markup

    rows.insert(
        0,
        [
            InlineKeyboardButton(
                text="🧭 Настроить VPN",
                callback_data=callback_data,
            )
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _target_message(messageable) -> Optional[Message]:
    if isinstance(messageable, Message):
        return messageable
    return getattr(messageable, "message", None)


def _viewer_id(messageable) -> Optional[int]:
    user = getattr(messageable, "from_user", None)
    return user.id if user else None


def _build_markup(
    key_id: int | str,
    fallback_markup: Optional[InlineKeyboardMarkup],
) -> Optional[InlineKeyboardMarkup]:
    try:
        from bot.utils.page_renderer import build_page_keyboard

        page_markup = build_page_keyboard(
            KEY_DELIVERY_PAGE,
            context={"key_id": key_id},
        )
    except Exception as exc:
        logger.warning("Could not build key-card keyboard: %s", exc)
        page_markup = None

    return add_onboarding_button(page_markup or fallback_markup, key_id)


def _remember_context(
    messageable,
    rendered_message: Message,
    raw_value: str,
    key_id: int | str,
) -> None:
    viewer_id = _viewer_id(messageable)
    if not viewer_id:
        return

    try:
        from config import ADMIN_IDS
        from bot.services.page_context import remember_page_context

        if viewer_id not in ADMIN_IDS:
            return
        remember_page_context(
            viewer_id,
            page_key=KEY_DELIVERY_PAGE,
            message=rendered_message,
            context={
                KEY_DELIVERY_CONTEXT_RAW: raw_value,
                KEY_DELIVERY_CONTEXT_KIND: "subscription",
                KEY_DELIVERY_CONTEXT_IS_NEW: False,
                KEY_DELIVERY_CONTEXT_ATTACH_MARKUP: True,
                KEY_CARD_CONTEXT_KEY_ID: key_id,
            },
            text_replacements=build_key_delivery_replacements(raw_value),
        )
    except Exception as exc:
        logger.warning("Could not remember onboarding key-card context: %s", exc)


async def render_subscription_key_card(
    messageable,
    raw_value: str,
    key_id: int | str,
    *,
    fallback_markup: Optional[InlineKeyboardMarkup] = None,
    remember: bool = True,
) -> Message:
    """Render a subscription URL with QR and a selected-key onboarding button."""
    from bot.utils.message_editor import get_message_data
    from bot.utils.text import safe_edit_or_send

    target = _target_message(messageable)
    if target is None:
        raise ValueError("Не удалось определить сообщение для выдачи ключа")

    page_data = get_message_data(KEY_DELIVERY_PAGE, KEY_CARD_TEXT)
    caption = build_key_card_caption(page_data.get("text"), raw_value)
    markup = _build_markup(key_id, fallback_markup)
    photo = BufferedInputFile(generate_qr_code(raw_value), filename="subscription_qr.png")

    rendered = await safe_edit_or_send(
        target,
        caption,
        reply_markup=markup,
        photo=photo,
    )
    if remember:
        _remember_context(messageable, rendered, raw_value, key_id)
    return rendered


async def send_subscription_key_card(
    messageable,
    key_data: dict,
    fallback_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    """Resolve, verify, and render the subscription URL for an existing key."""
    from bot.services.subscription_readiness import wait_for_subscription_ready
    from bot.services.vpn_api import get_subscription_url_for_key
    from bot.utils import key_sender_core

    key_id = key_data.get("id")
    if key_id is None:
        await key_sender_core._send_error(
            messageable,
            "Не удалось определить выбранный ключ.",
            fallback_markup,
        )
        return None

    try:
        raw_value = await get_subscription_url_for_key(key_data)
        if not raw_value:
            raise RuntimeError("empty subscription URL")

        ready = await wait_for_subscription_ready(
            raw_value,
            key_id=key_id,
            server_id=key_data.get("server_id"),
        )
        if not ready:
            await key_sender_core._send_error(
                messageable,
                "Ключ сохранён, но сервер всё ещё подготавливает данные подключения. "
                "Подождите немного и нажмите «Показать ключ» ещё раз.",
                fallback_markup,
            )
            return None

        return await render_subscription_key_card(
            messageable,
            raw_value,
            key_id,
            fallback_markup=fallback_markup,
        )
    except Exception as exc:
        logger.warning(
            "Could not render key card for key_id=%s error=%s",
            key_id,
            type(exc).__name__,
        )
        await key_sender_core._send_error(
            messageable,
            "Не удалось получить данные подключения. Повторите позже или обратитесь в поддержку.",
            fallback_markup,
        )
        return None


async def rerender_subscription_key_card(page_context, viewer_id: int) -> bool:
    """Keep the onboarding button after an administrator edits the card."""
    context = page_context.context or {}
    raw_value = context.get(KEY_DELIVERY_CONTEXT_RAW)
    key_id = context.get(KEY_CARD_CONTEXT_KEY_ID)
    if not raw_value or key_id is None:
        return False

    await render_subscription_key_card(
        page_context.message,
        raw_value,
        key_id,
        remember=False,
    )
    return True
