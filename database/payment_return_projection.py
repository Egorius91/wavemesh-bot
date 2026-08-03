"""Atomic SQLite projection updates for SaaS payment returns."""

from __future__ import annotations

from typing import Any

from .connection import get_db

__all__ = ["refresh_materialized_key_from_saas"]


def refresh_materialized_key_from_saas(
    *,
    key_id: int,
    tariff_id: int,
    expires_at: Any,
    traffic_limit: int,
) -> bool:
    """Apply one verified SaaS renewal snapshot in a single transaction.

    The SaaS access remains authoritative for expiry, tariff and traffic limit.
    A new paid period resets local traffic counters atomically with those fields.
    This helper deliberately does not schedule a shadow write back to SaaS.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE vpn_keys
            SET tariff_id = ?,
                expires_at = ?,
                traffic_limit = ?,
                traffic_used = 0,
                traffic_updated_at = NULL,
                traffic_notified_pct = 100
            WHERE id = ?
            """,
            (
                int(tariff_id),
                str(expires_at),
                max(0, int(traffic_limit)),
                int(key_id),
            ),
        )
        return cursor.rowcount == 1
