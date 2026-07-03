"""User expiry notification helpers for WaveMesh.

This module contains the safer WaveMesh-specific implementation of expiry
notifications. It avoids leaking None/null key names into user-facing text and
formats zero days as "сегодня".
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.requests import (
    get_expiring_keys,
    get_setting,
    is_notification_sent_today,
    log_notification_sent,
    mark_user_bot_blocked,
)
from bot.utils.delivery import is_bot_blocked_error

logger = logging.getLogger(__name__)


_EMPTY_NAME_MARKERS = {"", "none", "null", "nil", "undefined"}


def _clean_key_name(value: Any) -> str:
    """Returns a safe display name or an empty string when no name is available."""
    if value is None:
        return ""

    text = str(value).strip()
    if text.lower() in _EMPTY_NAME_MARKERS:
        return ""

    return text


def _day_word(days: int) -> str:
    """Russian plural form for 'день'."""
    value = abs(int(days))
    last_two = value % 100
    last_one = value % 10

    if 11 <= last_two <= 14:
        return "дней"
    if last_one == 1:
        return "день"
    if 2 <= last_one <= 4:
        return "дня"
    return "дней"


def _expiry_phrase(days_left: int) -> str:
    """Human-readable expiry phrase."""
    days_left = int(days_left)
    if days_left <= 0:
        return "сегодня"
    return f"через {days_left} {_day_word(days_left)}"


def _replace_zero_days(text: str) -> str:
    """Converts old custom wording like 'через 0 дней' into 'сегодня'."""
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        return "Сегодня" if raw[:1].isupper() else "сегодня"

    text = re.sub(r"\b[Чч]ерез\s+0\s+дн(?:ей|я|ь)\b", replace, text)
    text = re.sub(r"\b0\s+дн(?:ей|я|ь)\b", "сегодня", text, flags=re.IGNORECASE)
    return text


def _cleanup_missing_name_artifacts(text: str) -> str:
    """Removes visual artifacts caused by missing key names in custom templates."""
    text = re.sub(r"(?i)\bnone\b", "", text)
    text = re.sub(r"(?i)\bnull\b", "", text)
    text = text.replace("«»", "").replace("\"\"", "")
    text = re.sub(r"[ \t]+([,.!?;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()


def _postprocess_notification_text(text: str) -> str:
    text = _replace_zero_days(text)
    text = _cleanup_missing_name_artifacts(text)
    return text


def _notification_keyboard():
    """Inline keyboard for expiry notifications."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="my_keys"))
    builder.row(InlineKeyboardButton(text="🔑 Мои ключи", callback_data="my_keys"))
    builder.row(InlineKeyboardButton(text="🈴 На главную", callback_data="start"))
    return builder.as_markup()


async def check_and_send_expiry_notifications(bot: Bot) -> None:
    """
    Checks and sends notifications about expiring VPN keys.

    Также запускает проверку подписок с наступившим next_charge_at. Эта функция
    уже вызывается ежедневным планировщиком, поэтому автосписания работают без
    отдельной задачи в main.py.
    """
    logger.info("⏳ Запуск проверки истекающих ключей...")
    try:
        try:
            from bot.services.subscription_billing import process_due_subscriptions
            await process_due_subscriptions(bot)
        except Exception as recurring_error:
            logger.error("Ошибка автосписаний подписок: %s", recurring_error, exc_info=True)

        from bot.utils.message_editor import get_message_data
        from bot.utils.placeholders import apply_placeholder_replacements
        from bot.utils.text import escape_html, send_media_or_text

        days = int(get_setting("notification_days", "3"))

        default_notification = (
            "⚠️ <b>Ваша подписка скоро истекает</b>\n\n"
            "Срок действия закончится %срок%.\n\n"
            "Продлите подписку заранее, чтобы сохранить доступ к VPN без перерыва."
        )
        notification_data = get_message_data("notification_text", default_notification)
        notification_text = notification_data.get("text", default_notification)
        notification_media = notification_data.get("media_file_id")
        notification_media_type = notification_data.get("media_type")

        expiring_keys = get_expiring_keys(days)
        sent_count = 0
        kb = _notification_keyboard()

        for key_info in expiring_keys:
            vpn_key_id = key_info["vpn_key_id"]
            user_telegram_id = key_info["user_telegram_id"]
            days_left = int(key_info.get("days_left", 0) or 0)
            key_name = _clean_key_name(key_info.get("custom_name"))
            expiry_phrase = _expiry_phrase(days_left)

            if is_notification_sent_today(vpn_key_id):
                continue

            text = apply_placeholder_replacements(notification_text, {
                "%дней%": escape_html(str(days_left)),
                "%срок%": escape_html(expiry_phrase),
                "%срокистечения%": escape_html(expiry_phrase),
                "%имяключа%": escape_html(key_name),
            })
            text = _postprocess_notification_text(text)

            try:
                await send_media_or_text(
                    bot,
                    chat_id=user_telegram_id,
                    text=text,
                    media=notification_media,
                    media_type=notification_media_type,
                    reply_markup=kb,
                )
                log_notification_sent(vpn_key_id)
                sent_count += 1
            except Exception as e:
                if is_bot_blocked_error(e):
                    mark_user_bot_blocked(user_telegram_id)
                    logger.info("Пользователь %s помечен как заблокировавший бота", user_telegram_id)
                else:
                    logger.warning("Не удалось отправить уведомление пользователю %s: %s", user_telegram_id, e)

            await asyncio.sleep(0.3)

        if sent_count > 0:
            logger.info("📬 Отправлено %s уведомлений об истечении ключей", sent_count)
        else:
            logger.info("Нет ключей требующих уведомления")

    except Exception as e:
        logger.error("Ошибка в check_and_send_expiry_notifications: %s", e)
