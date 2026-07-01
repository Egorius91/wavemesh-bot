"""Update WaveMesh user help page and external links.

Run from the project root after deployment:

    .venv/bin/python scripts/update_help_page.py

The script updates both default and custom page fields so an already deployed bot
immediately stops showing legacy third-party support/news/help links.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "wavemesh_bot.db"

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
    "Поддержка: @wavemesh\n"
    "Новости: https://t.me/WaveMeshVPN"
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
            "action_value": "https://t.me/WaveMeshVPN",
        },
        {
            "id": "btn_support",
            "label": "💬 Поддержка",
            "color": "secondary",
            "row": 0,
            "col": 1,
            "is_hidden": False,
            "action_type": "url",
            "action_value": "https://t.me/wavemesh",
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


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO pages (page_key, text_default, buttons_default)
            VALUES ('help', ?, ?)
            """,
            (HELP_TEXT, HELP_BUTTONS),
        )
        conn.execute(
            """
            UPDATE pages
            SET text_default = ?,
                buttons_default = ?,
                text_custom = ?,
                buttons_custom = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE page_key = 'help'
            """,
            (HELP_TEXT, HELP_BUTTONS, HELP_TEXT, HELP_BUTTONS),
        )
        conn.commit()
    finally:
        conn.close()

    print("WaveMesh help page updated")


if __name__ == "__main__":
    main()
