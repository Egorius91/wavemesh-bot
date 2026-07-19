"""Absolute VPN-key expiry helpers used by recurring billing."""

from datetime import datetime, timezone
from typing import Any, Optional

from .connection import get_db

__all__ = ['get_vpn_key_expiry', 'set_vpn_key_expiry']


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')


def get_vpn_key_expiry(key_id: int) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT expires_at FROM vpn_keys WHERE id = ?",
            (key_id,),
        ).fetchone()
        return row['expires_at'] if row else None


def set_vpn_key_expiry(key_id: int, expires_at: Any) -> bool:
    formatted = _format_datetime(expires_at)
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE vpn_keys SET expires_at = ? WHERE id = ?",
            (formatted, key_id),
        )
        return cursor.rowcount > 0
