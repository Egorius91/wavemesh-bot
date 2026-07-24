"""Transactional key deletion with a durable access-shadow tombstone."""

from __future__ import annotations

import logging
from dataclasses import replace

from bot.services.access_shadow import get_access_shadow_snapshot
from bot.services.access_shadow_outbox import (
    enqueue_access_shadow_snapshot,
    start_access_shadow_outbox_worker,
)
from database.connection import get_db

logger = logging.getLogger(__name__)

__all__ = ["delete_vpn_key"]


def delete_vpn_key(key_id: int) -> bool:
    """Deletes a key and commits its sanitized tombstone in one transaction."""
    snapshot = get_access_shadow_snapshot(int(key_id))
    if snapshot is None:
        return False

    tombstone = replace(
        snapshot,
        enabled=False,
        configured=False,
        subscription_ready=False,
    )

    with get_db() as conn:
        # Preserve payment history and satisfy the same foreign-key ordering as
        # the legacy delete implementation.
        conn.execute(
            "UPDATE payments SET vpn_key_id = NULL WHERE vpn_key_id = ?",
            (int(key_id),),
        )
        conn.execute(
            "DELETE FROM notification_log WHERE vpn_key_id = ?",
            (int(key_id),),
        )
        cursor = conn.execute(
            "DELETE FROM vpn_keys WHERE id = ?",
            (int(key_id),),
        )
        if cursor.rowcount <= 0:
            return False

        enqueue_access_shadow_snapshot(
            tombstone,
            reason="delete",
            conn=conn,
        )

    logger.info(
        "Ключ ID %s удален из БД; access shadow tombstone queued",
        key_id,
    )
    # Delivery is non-blocking. The persisted row survives process restarts.
    start_access_shadow_outbox_worker()
    return True
