"""WaveMesh branding defaults.

This module keeps user-visible help links independent from the original project.
It is intentionally idempotent and safe to run on every bot startup.
"""

from __future__ import annotations

import json
import logging

from database.connection import get_db

logger = logging.getLogger(__name__)

SUPPORT_URL = "https://t.me/wavemesh"
NEWS_URL = "https://t.me/WaveMeshVPN"

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
    "💬 Поддержка: @wavemesh\n"
    "📢 Новости: https://t.me/WaveMeshVPN"
)

HELP_BUTTONS = json.dumps(
    [
        {
            "id": "btn_news",
            "label": "📢 Новости",
            "color": "secondary",
            "row": 0,
            "col": 0,
            "is_hidden": False,
            "action_type": "url",
            "action_value": NEWS_URL,
        },
        {
            "id": "btn_support",
            "label": "💬 Поддержка",
            "color": "secondary",
            "row": 0,
            "col": 1,
            "is_hidden": False,
            "action_type": "url",
            "action_value": SUPPORT_URL,
        },
        {
            "id": "btn_back_main",
            "label": "🈴 На главную",
            "color": "secondary",
            "row": 1,
            "col": 0,
            "is_hidden": False,
            "action_type": "internal",
            "action_value": "cmd_back_main",
        },
    ],
    ensure_ascii=False,
)

LEGACY_MARKERS = (
    "plushkin",
    "Yadreno",
    "yadreno",
    "telegra.ph/Kak-nastroit-VPN-Gajd-za-2-minuty-01-23",
)


def _needs_replacement(value: str | None) -> bool:
    if not value:
        return True
    return any(marker in value for marker in LEGACY_MARKERS)


def apply_wavemesh_branding_defaults() -> None:
    """Apply WaveMesh help/news/support links to the pages table.

    Existing custom fields are replaced only when they are empty or still contain
    legacy project markers. This preserves intentionally edited custom pages.
    """
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO pages (page_key, text_default, buttons_default)
            VALUES ('help', ?, ?)
            """,
            (HELP_TEXT, HELP_BUTTONS),
        )

        row = conn.execute(
            """
            SELECT text_custom, buttons_custom
            FROM pages
            WHERE page_key = 'help'
            """
        ).fetchone()

        text_custom = row["text_custom"] if row else None
        buttons_custom = row["buttons_custom"] if row else None

        update_custom_text = _needs_replacement(text_custom)
        update_custom_buttons = _needs_replacement(buttons_custom)

        conn.execute(
            """
            UPDATE pages
            SET text_default = ?,
                buttons_default = ?,
                text_custom = CASE WHEN ? THEN ? ELSE text_custom END,
                buttons_custom = CASE WHEN ? THEN ? ELSE buttons_custom END,
                updated_at = CURRENT_TIMESTAMP
            WHERE page_key = 'help'
            """,
            (
                HELP_TEXT,
                HELP_BUTTONS,
                1 if update_custom_text else 0,
                HELP_TEXT,
                1 if update_custom_buttons else 0,
                HELP_BUTTONS,
            ),
        )

    logger.info("WaveMesh branding defaults applied: help/support/news")
