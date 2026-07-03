"""Однократная проверка подписки на официальный Telegram-канал WaveMesh.

Механика мягкая: пользователь проходит проверку один раз при первом запуске.
После успешной проверки доступ не блокируется повторно, даже если пользователь позже отпишется.
"""
import logging
import sqlite3
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.connection import get_db
from database.db_settings import get_setting
from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)

DEFAULT_CHANNEL_USERNAME = "@WaveMeshVPN"
DEFAULT_CHANNEL_URL = "https://t.me/WaveMeshVPN"
DEFAULT_GATE_TEXT = (
    "📢 <b>Перед началом подпишитесь на официальный канал WaveMesh.</b>\n\n"
    "Там мы публикуем важные уведомления: обновления сервиса, инструкции, "
    "изменения способов оплаты и сообщения о технических работах.\n\n"
    "После подписки нажмите «Проверить подписку»."
)

VALID_MEMBER_STATUSES = {"creator", "administrator", "member"}


def _get_config_attr(name: str, default):
    try:
        import config  # type: ignore
        return getattr(config, name, default)
    except Exception:
        return default


def _add_column_if_missing(table: str, column_def: str) -> None:
    try:
        with get_db() as conn:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" in str(exc).lower():
            return
        raise


def ensure_channel_gate_columns() -> None:
    """Гарантирует наличие полей проверки подписки в таблице users."""
    _add_column_if_missing("users", "telegram_channel_checked INTEGER DEFAULT 0")
    _add_column_if_missing("users", "telegram_channel_checked_at DATETIME")
    _add_column_if_missing("users", "telegram_channel_username TEXT")


def _setting_bool(key: str, default: bool) -> bool:
    default_value = "1" if default else "0"
    value = (get_setting(key, default_value) or default_value).strip().lower()
    return value in {"1", "true", "yes", "on", "да", "вкл"}


def is_channel_gate_enabled() -> bool:
    default_enabled = bool(_get_config_attr("CHANNEL_GATE_ENABLED", True))
    return _setting_bool("channel_gate_enabled", default_enabled)


def get_channel_username() -> str:
    default_username = _get_config_attr("CHANNEL_GATE_USERNAME", DEFAULT_CHANNEL_USERNAME)
    return (get_setting("channel_gate_username", default_username) or default_username).strip()


def get_channel_url() -> str:
    default_url = _get_config_attr("CHANNEL_GATE_URL", DEFAULT_CHANNEL_URL)
    return (get_setting("channel_gate_url", default_url) or default_url).strip()


def get_channel_gate_text() -> str:
    default_text = _get_config_attr("CHANNEL_GATE_TEXT", DEFAULT_GATE_TEXT)
    return get_setting("channel_gate_text", default_text) or default_text


def has_passed_channel_gate(telegram_id: int) -> bool:
    """Проверяет, нужно ли показывать входной экран подписки."""
    if not is_channel_gate_enabled():
        return True

    ensure_channel_gate_columns()
    with get_db() as conn:
        row = conn.execute(
            "SELECT telegram_channel_checked FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
    return bool(row and row["telegram_channel_checked"])


def mark_channel_gate_passed(telegram_id: int) -> None:
    """Фиксирует успешную однократную проверку подписки."""
    ensure_channel_gate_columns()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE users
            SET telegram_channel_checked = 1,
                telegram_channel_checked_at = datetime('now'),
                telegram_channel_username = ?
            WHERE telegram_id = ?
            """,
            (get_channel_username(), telegram_id),
        )
    logger.info("Пользователь %s прошёл проверку подписки на канал", telegram_id)


async def verify_channel_subscription(bot: Bot, telegram_id: int) -> bool:
    """Проверяет текущий статус пользователя в официальном канале."""
    if not is_channel_gate_enabled():
        return True

    channel_username = get_channel_username()
    try:
        member = await bot.get_chat_member(chat_id=channel_username, user_id=telegram_id)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.warning(
            "Не удалось проверить подписку пользователя %s в канале %s: %s",
            telegram_id,
            channel_username,
            exc,
        )
        return False
    except Exception as exc:
        logger.exception(
            "Неожиданная ошибка проверки подписки пользователя %s в канале %s: %s",
            telegram_id,
            channel_username,
            exc,
        )
        return False

    status = getattr(member, "status", "")
    status_value = getattr(status, "value", status)
    return str(status_value) in VALID_MEMBER_STATUSES


def build_channel_gate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=get_channel_url())],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="channel_gate_check")],
        ]
    )


async def render_channel_gate(target: Message | CallbackQuery, *, force_new: bool = False) -> None:
    """Показывает экран подписки для Message или CallbackQuery."""
    text = get_channel_gate_text()
    reply_markup = build_channel_gate_keyboard()

    if isinstance(target, CallbackQuery):
        if target.message:
            await safe_edit_or_send(target.message, text, reply_markup=reply_markup, force_new=force_new)
        else:
            await target.bot.send_message(
                chat_id=target.from_user.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        return

    await safe_edit_or_send(target, text, reply_markup=reply_markup, force_new=force_new)
