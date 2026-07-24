"""Post-commit shadow-sync wrappers for legacy VPN-key mutations.

The underlying SQLite functions remain the source of truth. These wrappers
only schedule non-blocking SaaS read-model updates after a local mutation has
succeeded. They are re-exported from ``database.requests`` so existing
handlers keep the same public API.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any, Iterable, Optional

from database import db_keys as _db
from database.connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    "extend_vpn_key",
    "create_vpn_key_admin",
    "create_vpn_key_subscription_admin",
    "update_vpn_key_connection",
    "create_vpn_key",
    "create_initial_vpn_key",
    "bulk_update_traffic",
    "update_key_traffic",
    "reset_key_traffic_notification",
    "update_key_traffic_limit",
    "update_vpn_key_tariff_and_traffic_limit",
    "update_vpn_key_config",
    "update_vpn_key_sub_id",
    "delete_vpn_key",
    "add_days_to_first_active_key",
]

_background_tasks: set[asyncio.Task[Any]] = set()


def _schedule_key(key_id: int, *, reason: str) -> None:
    try:
        from bot.services.access_shadow import schedule_key_access_shadow_sync

        schedule_key_access_shadow_sync(int(key_id), reason=reason)
    except Exception:
        logger.exception(
            "Failed to schedule access shadow sync: key_id=%s reason=%s",
            key_id,
            reason,
        )


def _schedule_keys(key_ids: Iterable[int], *, reason: str) -> None:
    for key_id in dict.fromkeys(int(value) for value in key_ids):
        _schedule_key(key_id, reason=reason)


def _capture_snapshot(key_id: int):
    try:
        from bot.services.access_shadow import (
            access_shadow_sync_enabled,
            get_access_shadow_snapshot,
            internal_api_client,
        )

        if not access_shadow_sync_enabled() or not internal_api_client.configured:
            return None
        return get_access_shadow_snapshot(int(key_id))
    except Exception:
        logger.exception(
            "Failed to capture access shadow snapshot before delete: key_id=%s",
            key_id,
        )
        return None


def _schedule_snapshot(snapshot: Any, *, reason: str) -> None:
    if snapshot is None:
        return

    try:
        from bot.services.access_shadow import (
            InternalApiError,
            access_shadow_sync_enabled,
            internal_api_client,
            sync_access_shadow_snapshot,
        )
    except Exception:
        logger.exception(
            "Failed to import access shadow scheduler: key_id=%s reason=%s",
            getattr(snapshot, "legacy_key_id", None),
            reason,
        )
        return

    if not access_shadow_sync_enabled() or not internal_api_client.configured:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def runner() -> None:
        try:
            await sync_access_shadow_snapshot(snapshot, reason=reason)
        except InternalApiError as error:
            logger.warning(
                "WaveMesh access shadow tombstone sync failed: key_id=%s "
                "reason=%s code=%s status=%s retryable=%s",
                snapshot.legacy_key_id,
                reason,
                error.code,
                error.status,
                error.retryable,
            )
        except Exception:
            logger.exception(
                "Unexpected WaveMesh access shadow tombstone sync error: "
                "key_id=%s reason=%s",
                snapshot.legacy_key_id,
                reason,
            )

    task = loop.create_task(
        runner(),
        name=f"access-shadow-snapshot-{snapshot.legacy_key_id}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _first_active_key_id(user_id: int) -> int | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM vpn_keys
            WHERE user_id = ? AND expires_at > datetime('now')
            ORDER BY expires_at DESC
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
    return int(row["id"]) if row else None


def extend_vpn_key(key_id: int, days: int) -> bool:
    success = _db.extend_vpn_key(key_id, days)
    if success:
        _schedule_key(key_id, reason="extend")
    return success


def create_vpn_key_admin(
    user_id: int,
    server_id: int,
    tariff_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str,
    days: int,
    traffic_limit: int = 0,
) -> int:
    key_id = _db.create_vpn_key_admin(
        user_id,
        server_id,
        tariff_id,
        panel_inbound_id,
        panel_email,
        client_uuid,
        days,
        traffic_limit,
    )
    _schedule_key(key_id, reason="create_admin")
    return key_id


def create_vpn_key_subscription_admin(
    user_id: int,
    server_id: int,
    tariff_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str,
    sub_id: str,
    days: int,
    traffic_limit: int = 0,
) -> int:
    key_id = _db.create_vpn_key_subscription_admin(
        user_id,
        server_id,
        tariff_id,
        panel_inbound_id,
        panel_email,
        client_uuid,
        sub_id,
        days,
        traffic_limit,
    )
    _schedule_key(key_id, reason="create_subscription_admin")
    return key_id


def create_vpn_key(
    user_id: int,
    server_id: int,
    tariff_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str,
    days: int,
    traffic_limit: int = 0,
) -> int:
    key_id = _db.create_vpn_key(
        user_id,
        server_id,
        tariff_id,
        panel_inbound_id,
        panel_email,
        client_uuid,
        days,
        traffic_limit,
    )
    _schedule_key(key_id, reason="create")
    return key_id


def create_initial_vpn_key(
    user_id: int,
    tariff_id: int,
    days: int,
    traffic_limit: int = 0,
) -> int:
    key_id = _db.create_initial_vpn_key(
        user_id,
        tariff_id,
        days,
        traffic_limit,
    )
    _schedule_key(key_id, reason="create_initial")
    return key_id


def update_vpn_key_connection(
    key_id: int,
    server_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str,
    sub_id: Optional[str] = ...,
) -> bool:
    success = _db.update_vpn_key_connection(
        key_id,
        server_id,
        panel_inbound_id,
        panel_email,
        client_uuid,
        sub_id,
    )
    if success:
        _schedule_key(key_id, reason="connection")
    return success


def update_vpn_key_config(
    key_id: int,
    server_id: int,
    panel_inbound_id: int,
    panel_email: str,
    client_uuid: str,
    sub_id: Optional[str] = ...,
) -> bool:
    success = _db.update_vpn_key_config(
        key_id,
        server_id,
        panel_inbound_id,
        panel_email,
        client_uuid,
        sub_id,
    )
    if success:
        _schedule_key(key_id, reason="config")
    return success


def update_vpn_key_sub_id(key_id: int, sub_id: Optional[str]) -> bool:
    success = _db.update_vpn_key_sub_id(key_id, sub_id)
    if success:
        _schedule_key(key_id, reason="subscription_readiness")
    return success


def bulk_update_traffic(updates: list[tuple]) -> None:
    _db.bulk_update_traffic(updates)
    if updates:
        _schedule_keys((key_id for _, key_id in updates), reason="traffic_bulk")


def update_key_traffic(key_id: int, traffic_used: int) -> None:
    _db.update_key_traffic(key_id, traffic_used)
    _schedule_key(key_id, reason="traffic")


def reset_key_traffic_notification(key_id: int) -> None:
    _db.reset_key_traffic_notification(key_id)
    _schedule_key(key_id, reason="traffic_reset")


def update_key_traffic_limit(key_id: int, traffic_limit_bytes: int) -> None:
    _db.update_key_traffic_limit(key_id, traffic_limit_bytes)
    _schedule_key(key_id, reason="traffic_limit")


def update_vpn_key_tariff_and_traffic_limit(
    key_id: int,
    tariff_id: int,
    traffic_limit_bytes: int,
) -> bool:
    success = _db.update_vpn_key_tariff_and_traffic_limit(
        key_id,
        tariff_id,
        traffic_limit_bytes,
    )
    if success:
        _schedule_key(key_id, reason="tariff")
    return success


def delete_vpn_key(key_id: int) -> bool:
    snapshot = _capture_snapshot(key_id)
    success = _db.delete_vpn_key(key_id)
    if success and snapshot is not None:
        tombstone = replace(
            snapshot,
            enabled=False,
            configured=False,
            subscription_ready=False,
        )
        _schedule_snapshot(tombstone, reason="delete")
    return success


def add_days_to_first_active_key(user_id: int, days: int) -> bool:
    key_id = _first_active_key_id(user_id)
    success = _db.add_days_to_first_active_key(user_id, days)
    if success and key_id is not None:
        _schedule_key(key_id, reason="referral_extend")
    return success
