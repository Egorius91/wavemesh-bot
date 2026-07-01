"""WaveMesh branding defaults.

This module keeps user-visible texts and links independent from the original
project. It is intentionally idempotent and safe to run on every bot startup.
"""

from __future__ import annotations

import json
import logging

from database.connection import get_db

logger = logging.getLogger(__name__)

PROJECT_NAME = "WaveMesh VPN"
SUPPORT_USERNAME = "@wavemesh"
SUPPORT_URL = "https://t.me/wavemesh"
NEWS_URL = "https://t.me/WaveMeshVPN"

MAIN_TEXT = (
    "🌊 <b>Добро пожаловать в WaveMesh VPN</b>\n\n"
    "Быстрый и стабильный VPN-доступ для ваших устройств.\n"
    "Выберите тариф, получите ключ и подключайтесь за пару минут.\n\n"
    "%тарифы%"
)

MAIN_BUTTONS = json.dumps(
    [
        {"id": "btn_my_keys",  "label": "🔑 Мои ключи",        "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_my_keys"},
        {"id": "btn_buy_key",  "label": "💳 Купить ключ",       "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "internal", "action_value": "cmd_buy"},
        {"id": "btn_trial",    "label": "🎁 Пробный доступ",    "color": "secondary", "row": 1, "col": 0, "is_hidden": True,  "action_type": "internal", "action_value": "cmd_trial"},
        {"id": "btn_referral", "label": "🔗 Реферальная ссылка", "color": "secondary", "row": 2, "col": 0, "is_hidden": True,  "action_type": "internal", "action_value": "cmd_referral"},
        {"id": "btn_help",     "label": "❓ Справка",            "color": "secondary", "row": 2, "col": 1, "is_hidden": False, "action_type": "internal", "action_value": "cmd_help"},
    ],
    ensure_ascii=False,
)

HELP_TEXT = (
    "🔐 <b>Как подключить WaveMesh VPN</b>\n\n"
    "1. Оформите подписку или активируйте пробный доступ.\n"
    "2. Откройте раздел «Мои ключи» и выберите свой ключ.\n"
    "3. Скопируйте ссылку подключения или импортируйте её в VPN-клиент.\n"
    "4. Включите подключение и дождитесь статуса Connected.\n\n"
    "<b>Рекомендуемые клиенты:</b>\n"
    "• iPhone / iPad: Happ, Streisand или V2Box.\n"
    "• Android: Happ, v2rayNG или Hiddify.\n"
    "• Windows / macOS: Hiddify, Happ или совместимый клиент.\n\n"
    "Если подключение не работает, обновите ключ в боте, проверьте активность подписки "
    "и попробуйте другой клиент или сервер.\n\n"
    f"💬 Поддержка: {SUPPORT_USERNAME}\n"
    f"📢 Новости: {NEWS_URL}"
)

HELP_BUTTONS = json.dumps(
    [
        {"id": "btn_news",      "label": "📢 Новости",    "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": NEWS_URL},
        {"id": "btn_support",   "label": "💬 Поддержка",  "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "url", "action_value": SUPPORT_URL},
        {"id": "btn_back_main", "label": "🈴 На главную", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_back_main"},
    ],
    ensure_ascii=False,
)

PREPAYMENT_TEXT = (
    "💳 <b>Купить ключ WaveMesh VPN</b>\n\n"
    "🔐 <b>Что вы получаете:</b>\n"
    "• доступ к VPN-серверам и поддерживаемым протоколам;\n"
    "• личный ключ для подключения;\n"
    "• управление подпиской прямо в Telegram;\n"
    "• поддержку по вопросам подключения.\n\n"
    "⚠️ <b>Важно:</b>\n"
    "• ключ предназначен для личного использования;\n"
    "• стабильность соединения может зависеть от устройства, сети и выбранного клиента;\n"
    "• если возникнут трудности с подключением, напишите в поддержку.\n\n"
    "<i>Выберите удобный способ оплаты ниже.</i>"
)

TRIAL_TEXT = (
    "🎁 <b>Пробный доступ WaveMesh VPN</b>\n\n"
    "Пробный период позволяет проверить подключение и скорость перед покупкой.\n\n"
    "Нажмите кнопку ниже, чтобы активировать тестовый доступ.\n\n"
    "<i>Пробный период предоставляется один раз на аккаунт.</i>"
)

PAGE_DEFAULTS = {
    "main": (MAIN_TEXT, MAIN_BUTTONS),
    "help": (HELP_TEXT, HELP_BUTTONS),
    "prepayment": (PREPAYMENT_TEXT, None),
    "trial": (TRIAL_TEXT, None),
}

LEGACY_MARKERS = (
    "plushkin",
    "Yadreno",
    "yadreno",
    "VPN-бот",
    "telegra.ph/Kak-nastroit-VPN-Gajd-za-2-minuty-01-23",
)


def _needs_replacement(value: str | None) -> bool:
    if not value:
        return True
    return any(marker in value for marker in LEGACY_MARKERS)


def _update_page(page_key: str, text: str, buttons: str | None) -> None:
    with get_db() as conn:
        if buttons is None:
            existing = conn.execute(
                "SELECT buttons_default FROM pages WHERE page_key = ?",
                (page_key,),
            ).fetchone()
            buttons_to_insert = existing["buttons_default"] if existing else "[]"
        else:
            buttons_to_insert = buttons

        conn.execute(
            """
            INSERT OR IGNORE INTO pages (page_key, text_default, buttons_default)
            VALUES (?, ?, ?)
            """,
            (page_key, text, buttons_to_insert),
        )

        row = conn.execute(
            """
            SELECT text_custom, buttons_custom, buttons_default
            FROM pages
            WHERE page_key = ?
            """,
            (page_key,),
        ).fetchone()

        text_custom = row["text_custom"] if row else None
        buttons_custom = row["buttons_custom"] if row else None
        current_buttons_default = row["buttons_default"] if row else buttons_to_insert
        next_buttons = buttons if buttons is not None else current_buttons_default

        update_custom_text = _needs_replacement(text_custom)
        update_custom_buttons = buttons is not None and _needs_replacement(buttons_custom)

        conn.execute(
            """
            UPDATE pages
            SET text_default = ?,
                buttons_default = ?,
                text_custom = CASE WHEN ? THEN ? ELSE text_custom END,
                buttons_custom = CASE WHEN ? THEN ? ELSE buttons_custom END,
                updated_at = CURRENT_TIMESTAMP
            WHERE page_key = ?
            """,
            (
                text,
                next_buttons,
                1 if update_custom_text else 0,
                text,
                1 if update_custom_buttons else 0,
                next_buttons,
                page_key,
            ),
        )


def apply_wavemesh_branding_defaults() -> None:
    """Apply WaveMesh user-facing defaults to the pages table."""
    for page_key, (text, buttons) in PAGE_DEFAULTS.items():
        _update_page(page_key, text, buttons)

    logger.info("WaveMesh branding defaults applied to core user pages")
