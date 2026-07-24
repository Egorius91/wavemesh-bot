"""Durable SQLite outbox for WaveMesh access-shadow snapshots.

Events are stored in the legacy bot database and delivered asynchronously. The
outbox contains only the already-sanitized ``AccessShadowSnapshot`` fields.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from bot.services.access_shadow import AccessShadowSnapshot, sync_access_shadow_snapshot
from bot.services.internal_api import InternalApiError, internal_api_client
from database.connection import get_db

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 15
DEFAULT_BATCH_SIZE = 25
MAX_BATCH_SIZE = 100
MAX_RETRY_DELAY_SECONDS = 3600

_worker_task: asyncio.Task[Any] | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS access_shadow_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    legacy_key_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_access_shadow_outbox_due
    ON access_shadow_outbox (available_at, id);
"""


def _poll_seconds() -> int:
    raw = os.getenv("WAVEMESH_ACCESS_SHADOW_OUTBOX_POLL_SECONDS", str(DEFAULT_POLL_SECONDS))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_POLL_SECONDS


def _batch_size() -> int:
    raw = os.getenv("WAVEMESH_ACCESS_SHADOW_OUTBOX_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
    try:
        return min(MAX_BATCH_SIZE, max(1, int(raw)))
    except ValueError:
        return DEFAULT_BATCH_SIZE


def ensure_access_shadow_outbox_schema(conn: Any | None = None) -> None:
    """Creates the outbox table idempotently."""
    if conn is not None:
        conn.executescript(_SCHEMA)
        return
    with get_db() as owned_conn:
        owned_conn.executescript(_SCHEMA)


def _snapshot_payload(snapshot: AccessShadowSnapshot) -> dict[str, Any]:
    return {
        "telegram_id": snapshot.telegram_id,
        "legacy_key_id": snapshot.legacy_key_id,
        "username": snapshot.username,
        "display_name": snapshot.display_name,
        "is_bot_blocked": snapshot.is_bot_blocked,
        "expires_at": snapshot.expires_at,
        "enabled": snapshot.enabled,
        "configured": snapshot.configured,
        "subscription_ready": snapshot.subscription_ready,
        "device_limit": snapshot.device_limit,
        "traffic_limit_bytes": snapshot.traffic_limit_bytes,
        "traffic_used_bytes": snapshot.traffic_used_bytes,
    }


def _event_key(snapshot: AccessShadowSnapshot, reason: str) -> str:
    # A key can only be deleted once. A deterministic key makes retries and
    # repeated handler calls harmless while preserving the original payload.
    return f"{reason}:{snapshot.legacy_key_id}"


def enqueue_access_shadow_snapshot(
    snapshot: AccessShadowSnapshot,
    *,
    reason: str,
    conn: Any | None = None,
) -> bool:
    """Persists one sanitized snapshot, optionally inside a caller transaction."""
    payload_json = json.dumps(
        _snapshot_payload(snapshot),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )

    def insert(target: Any) -> bool:
        ensure_access_shadow_outbox_schema(target)
        cursor = target.execute(
            """
            INSERT OR IGNORE INTO access_shadow_outbox
                (event_key, legacy_key_id, reason, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                _event_key(snapshot, reason),
                int(snapshot.legacy_key_id),
                reason,
                payload_json,
            ),
        )
        return cursor.rowcount > 0

    if conn is not None:
        return insert(conn)
    with get_db() as owned_conn:
        return insert(owned_conn)


def _deserialize_snapshot(payload_json: str) -> AccessShadowSnapshot:
    payload = json.loads(payload_json)
    return AccessShadowSnapshot(
        telegram_id=int(payload["telegram_id"]),
        legacy_key_id=int(payload["legacy_key_id"]),
        username=payload.get("username"),
        display_name=payload.get("display_name"),
        is_bot_blocked=bool(payload.get("is_bot_blocked", False)),
        expires_at=payload.get("expires_at"),
        enabled=bool(payload.get("enabled", False)),
        configured=bool(payload.get("configured", False)),
        subscription_ready=bool(payload.get("subscription_ready", False)),
        device_limit=int(payload.get("device_limit", 1)),
        traffic_limit_bytes=str(payload.get("traffic_limit_bytes", "0")),
        traffic_used_bytes=str(payload.get("traffic_used_bytes", "0")),
    )


def _retry_delay_seconds(attempts: int, retryable: bool = True) -> int:
    base = 5 if retryable else 300
    exponent = min(max(0, attempts - 1), 10)
    return min(MAX_RETRY_DELAY_SECONDS, base * (2**exponent))


def _mark_delivered(event_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM access_shadow_outbox WHERE id = ?", (int(event_id),))


def _mark_failed(event_id: int, *, attempts: int, error: str, retryable: bool) -> None:
    delay = _retry_delay_seconds(attempts, retryable)
    with get_db() as conn:
        conn.execute(
            """
            UPDATE access_shadow_outbox
            SET attempts = ?,
                available_at = datetime('now', ?),
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (attempts, f"+{delay} seconds", error[:500], int(event_id)),
        )


def list_due_access_shadow_events(*, limit: int | None = None) -> list[Any]:
    ensure_access_shadow_outbox_schema()
    resolved_limit = min(MAX_BATCH_SIZE, max(1, int(limit or _batch_size())))
    with get_db() as conn:
        return conn.execute(
            """
            SELECT id, legacy_key_id, reason, payload_json, attempts
            FROM access_shadow_outbox
            WHERE available_at <= CURRENT_TIMESTAMP
            ORDER BY id ASC
            LIMIT ?
            """,
            (resolved_limit,),
        ).fetchall()


async def drain_access_shadow_outbox_once(*, limit: int | None = None) -> dict[str, int]:
    """Attempts one finite batch and leaves failures durably queued."""
    stats = {"selected": 0, "delivered": 0, "failed": 0}
    if not internal_api_client.configured:
        return stats

    for row in list_due_access_shadow_events(limit=limit):
        stats["selected"] += 1
        event_id = int(row["id"])
        attempts = int(row["attempts"] or 0) + 1
        try:
            snapshot = _deserialize_snapshot(row["payload_json"])
            await sync_access_shadow_snapshot(snapshot, reason=f"outbox_{row['reason']}")
            _mark_delivered(event_id)
            stats["delivered"] += 1
            logger.info(
                "WaveMesh access shadow outbox delivered: event_id=%s key_id=%s reason=%s attempts=%s",
                event_id,
                row["legacy_key_id"],
                row["reason"],
                attempts,
            )
        except InternalApiError as error:
            stats["failed"] += 1
            _mark_failed(
                event_id,
                attempts=attempts,
                error=f"{error.code}:{error.status}",
                retryable=bool(error.retryable),
            )
            logger.warning(
                "WaveMesh access shadow outbox delivery failed: event_id=%s key_id=%s reason=%s attempts=%s code=%s status=%s retryable=%s",
                event_id,
                row["legacy_key_id"],
                row["reason"],
                attempts,
                error.code,
                error.status,
                error.retryable,
            )
        except Exception as error:
            stats["failed"] += 1
            _mark_failed(
                event_id,
                attempts=attempts,
                error=type(error).__name__,
                retryable=True,
            )
            logger.exception(
                "Unexpected WaveMesh access shadow outbox delivery error: event_id=%s key_id=%s reason=%s attempts=%s",
                event_id,
                row["legacy_key_id"],
                row["reason"],
                attempts,
            )
    return stats


async def run_access_shadow_outbox_worker() -> None:
    ensure_access_shadow_outbox_schema()
    logger.info("WaveMesh access shadow outbox worker started")
    try:
        while True:
            await drain_access_shadow_outbox_once()
            await asyncio.sleep(_poll_seconds())
    except asyncio.CancelledError:
        logger.info("WaveMesh access shadow outbox worker stopped")
        raise


def start_access_shadow_outbox_worker() -> None:
    global _worker_task
    if not internal_api_client.configured:
        return
    if _worker_task is not None and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(
        run_access_shadow_outbox_worker(),
        name="access-shadow-outbox-worker",
    )


async def stop_access_shadow_outbox_worker() -> None:
    global _worker_task
    task = _worker_task
    _worker_task = None
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def pending_access_shadow_outbox_count() -> int:
    ensure_access_shadow_outbox_schema()
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM access_shadow_outbox").fetchone()
    return int(row["count"])
