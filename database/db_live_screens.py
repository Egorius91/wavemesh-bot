import logging
from typing import Any, Dict, Optional

from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'ensure_live_screen_schema',
    'get_live_screen',
    'save_live_screen',
    'clear_live_screen',
    'get_live_notice',
    'save_live_notice',
    'clear_live_notice',
]


def ensure_live_screen_schema() -> None:
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_live_screens (
                telegram_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                screen_key TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_live_notices (
                telegram_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                notice_key TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def get_live_screen(telegram_id: int) -> Optional[Dict[str, Any]]:
    ensure_live_screen_schema()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT telegram_id, chat_id, message_id, screen_key, created_at, updated_at
            FROM user_live_screens
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
        return _row_to_dict(row)


def save_live_screen(
    *,
    telegram_id: int,
    chat_id: int,
    message_id: int,
    screen_key: Optional[str] = None,
) -> None:
    ensure_live_screen_schema()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO user_live_screens (telegram_id, chat_id, message_id, screen_key)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                screen_key = excluded.screen_key,
                updated_at = CURRENT_TIMESTAMP
            """,
            (telegram_id, chat_id, message_id, screen_key),
        )


def clear_live_screen(telegram_id: int) -> bool:
    ensure_live_screen_schema()
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM user_live_screens WHERE telegram_id = ?",
            (telegram_id,),
        )
        return cursor.rowcount > 0


def get_live_notice(telegram_id: int) -> Optional[Dict[str, Any]]:
    ensure_live_screen_schema()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT telegram_id, chat_id, message_id, notice_key, created_at, updated_at
            FROM user_live_notices
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
        return _row_to_dict(row)


def save_live_notice(
    *,
    telegram_id: int,
    chat_id: int,
    message_id: int,
    notice_key: Optional[str] = None,
) -> None:
    ensure_live_screen_schema()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO user_live_notices (telegram_id, chat_id, message_id, notice_key)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                notice_key = excluded.notice_key,
                updated_at = CURRENT_TIMESTAMP
            """,
            (telegram_id, chat_id, message_id, notice_key),
        )


def clear_live_notice(telegram_id: int) -> bool:
    ensure_live_screen_schema()
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM user_live_notices WHERE telegram_id = ?",
            (telegram_id,),
        )
        return cursor.rowcount > 0
