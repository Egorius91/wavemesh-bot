"""Safe legacy VPN-key projection into the WaveMesh SaaS access read model."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from bot.services.internal_api import InternalApiError, internal_api_client
from database.connection import get_db

logger = logging.getLogger(__name__)

DEFAULT_BACKFILL_LIMIT = 50
MAX_BACKFILL_LIMIT = 500
_background_tasks: set[asyncio.Task[Any]] = set()


@dataclass(frozen=True)
class AccessShadowSnapshot:
    """Only non-secret fields allowed to leave the legacy Bot database."""

    telegram_id: int
    legacy_key_id: int
    username: str | None
    display_name: str | None
    is_bot_blocked: bool
    expires_at: str | None
    enabled: bool
    configured: bool
    subscription_ready: bool
    device_limit: int
    traffic_limit_bytes: str
    traffic_used_bytes: str

    def user_payload(self) -> dict[str, Any]:
        return {
            "telegram_id": self.telegram_id,
            "username": self.username,
            "display_name": self.display_name,
            "is_bot_blocked": self.is_bot_blocked,
        }

    def access_payload(self) -> dict[str, Any]:
        return {
            "telegram_id": str(self.telegram_id),
            "legacy_key_id": str(self.legacy_key_id),
            "expires_at": self.expires_at,
            "enabled": self.enabled,
            "configured": self.configured,
            "subscription_ready": self.subscription_ready,
            "device_limit": self.device_limit,
            "traffic_limit_bytes": self.traffic_limit_bytes,
            "traffic_used_bytes": self.traffic_used_bytes,
        }


def access_shadow_sync_enabled() -> bool:
    return os.getenv(
        "WAVEMESH_ACCESS_SHADOW_SYNC_ENABLED",
        "false",
    ).strip().lower() == "true"


def _backfill_limit() -> int:
    raw = os.getenv(
        "WAVEMESH_ACCESS_SHADOW_BACKFILL_LIMIT",
        str(DEFAULT_BACKFILL_LIMIT),
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_BACKFILL_LIMIT
    return min(MAX_BACKFILL_LIMIT, max(1, value))


def _iso_utc(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Access shadow ignored invalid expiry for a legacy key")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _device_limit(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return parsed if 1 <= parsed <= 100 else 1


def _display_name(first_name: Any, last_name: Any) -> str | None:
    value = " ".join(
        part.strip()
        for part in (first_name, last_name)
        if isinstance(part, str) and part.strip()
    )
    return value or None


def _snapshot_from_row(row: Any) -> AccessShadowSnapshot:
    return AccessShadowSnapshot(
        telegram_id=int(row["telegram_id"]),
        legacy_key_id=int(row["legacy_key_id"]),
        username=row["username"],
        display_name=_display_name(row["first_name"], row["last_name"]),
        is_bot_blocked=bool(row["is_bot_blocked"]),
        expires_at=_iso_utc(row["expires_at"]),
        enabled=bool(row["enabled"]),
        configured=bool(row["configured"]),
        subscription_ready=bool(row["subscription_ready"]),
        device_limit=_device_limit(row["max_ips"]),
        traffic_limit_bytes=str(max(0, int(row["traffic_limit"] or 0))),
        traffic_used_bytes=str(max(0, int(row["traffic_used"] or 0))),
    )


_SELECT_SNAPSHOT = """
    SELECT
        vk.id AS legacy_key_id,
        u.telegram_id,
        u.username,
        u.first_name,
        u.last_name,
        COALESCE(u.is_bot_blocked, 0) AS is_bot_blocked,
        vk.expires_at,
        COALESCE(vk.traffic_limit, 0) AS traffic_limit,
        COALESCE(vk.traffic_used, 0) AS traffic_used,
        COALESCE(t.max_ips, 1) AS max_ips,
        CASE
            WHEN (vk.expires_at IS NULL OR vk.expires_at > CURRENT_TIMESTAMP)
             AND (COALESCE(vk.traffic_limit, 0) <= 0
                  OR COALESCE(vk.traffic_used, 0) < COALESCE(vk.traffic_limit, 0))
            THEN 1 ELSE 0
        END AS enabled,
        CASE
            WHEN vk.server_id IS NOT NULL
             AND COALESCE(vk.client_uuid, '') <> ''
             AND COALESCE(vk.panel_email, '') <> ''
            THEN 1 ELSE 0
        END AS configured,
        CASE WHEN COALESCE(vk.sub_id, '') <> '' THEN 1 ELSE 0 END AS subscription_ready
    FROM vpn_keys vk
    JOIN users u ON u.id = vk.user_id
    LEFT JOIN tariffs t ON t.id = vk.tariff_id
"""


def get_access_shadow_snapshot(key_id: int) -> AccessShadowSnapshot | None:
    with get_db() as conn:
        row = conn.execute(
            f"{_SELECT_SNAPSHOT} WHERE vk.id = ? LIMIT 1",
            (int(key_id),),
        ).fetchone()
    return _snapshot_from_row(row) if row else None


def list_access_shadow_snapshots(
    *,
    telegram_id: int | None = None,
    limit: int | None = None,
) -> list[AccessShadowSnapshot]:
    resolved_limit = min(MAX_BACKFILL_LIMIT, max(1, int(limit or _backfill_limit())))
    params: list[Any] = []
    where = ""
    if telegram_id is not None:
        where = " WHERE u.telegram_id = ?"
        params.append(int(telegram_id))
    params.append(resolved_limit)

    with get_db() as conn:
        rows = conn.execute(
            f"{_SELECT_SNAPSHOT}{where} ORDER BY vk.id ASC LIMIT ?",
            params,
        ).fetchall()
    return [_snapshot_from_row(row) for row in rows]


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def _idempotency_key(prefix: str, stable_id: int, payload: dict[str, Any]) -> str:
    return f"{prefix}-{stable_id}-{_canonical_digest(payload)}"


async def sync_access_shadow_snapshot(
    snapshot: AccessShadowSnapshot,
    *,
    reason: str,
) -> dict[str, Any]:
    """Upserts the Telegram owner, then projects one safe access snapshot."""
    user_payload = snapshot.user_payload()
    await internal_api_client.upsert_telegram_user(
        telegram_id=snapshot.telegram_id,
        username=snapshot.username,
        display_name=snapshot.display_name,
        is_bot_blocked=snapshot.is_bot_blocked,
        idempotency_key=_idempotency_key(
            "access-shadow-user",
            snapshot.telegram_id,
            user_payload,
        ),
    )

    access_payload = snapshot.access_payload()
    result = await internal_api_client.sync_access_shadow(
        payload=access_payload,
        idempotency_key=_idempotency_key(
            "access-shadow-key",
            snapshot.legacy_key_id,
            access_payload,
        ),
    )
    logger.info(
        "WaveMesh access shadow sync completed: key_id=%s telegram_id=%s "
        "reason=%s status=%s created=%s desired_version=%s",
        snapshot.legacy_key_id,
        snapshot.telegram_id,
        reason,
        result.get("status"),
        result.get("created"),
        result.get("desired_version"),
    )
    return result


async def _sync_many(
    snapshots: Iterable[AccessShadowSnapshot],
    *,
    reason: str,
) -> dict[str, int]:
    stats = {"selected": 0, "synced": 0, "failed": 0}
    for snapshot in snapshots:
        stats["selected"] += 1
        try:
            await sync_access_shadow_snapshot(snapshot, reason=reason)
            stats["synced"] += 1
        except InternalApiError as error:
            stats["failed"] += 1
            logger.warning(
                "WaveMesh access shadow sync failed: key_id=%s telegram_id=%s "
                "reason=%s code=%s status=%s retryable=%s",
                snapshot.legacy_key_id,
                snapshot.telegram_id,
                reason,
                error.code,
                error.status,
                error.retryable,
            )
        except Exception:
            stats["failed"] += 1
            logger.exception(
                "Unexpected WaveMesh access shadow sync error: key_id=%s "
                "telegram_id=%s reason=%s",
                snapshot.legacy_key_id,
                snapshot.telegram_id,
                reason,
            )
    return stats


async def sync_user_access_shadows(
    telegram_id: int,
    *,
    limit: int = 100,
    reason: str = "my_keys",
) -> dict[str, int]:
    if not access_shadow_sync_enabled() or not internal_api_client.configured:
        return {"selected": 0, "synced": 0, "failed": 0}
    snapshots = list_access_shadow_snapshots(
        telegram_id=telegram_id,
        limit=limit,
    )
    return await _sync_many(snapshots, reason=reason)


async def run_access_shadow_backfill() -> dict[str, int]:
    if not access_shadow_sync_enabled() or not internal_api_client.configured:
        logger.info("WaveMesh access shadow backfill is disabled")
        return {"selected": 0, "synced": 0, "failed": 0}

    stats = await _sync_many(
        list_access_shadow_snapshots(limit=_backfill_limit()),
        reason="startup_backfill",
    )
    logger.info("WaveMesh access shadow backfill completed: %s", stats)
    return stats


def _schedule(coro: Any, *, name: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def schedule_key_access_shadow_sync(key_id: int, *, reason: str) -> None:
    """Schedules one non-blocking key projection from its current DB state."""
    if not access_shadow_sync_enabled() or not internal_api_client.configured:
        return

    async def runner() -> None:
        snapshot = get_access_shadow_snapshot(int(key_id))
        if not snapshot:
            logger.warning(
                "WaveMesh access shadow sync skipped missing key: key_id=%s reason=%s",
                key_id,
                reason,
            )
            return
        try:
            await sync_access_shadow_snapshot(snapshot, reason=reason)
        except InternalApiError as error:
            logger.warning(
                "WaveMesh access shadow scheduled sync failed: key_id=%s reason=%s "
                "code=%s status=%s retryable=%s",
                key_id,
                reason,
                error.code,
                error.status,
                error.retryable,
            )
        except Exception:
            logger.exception(
                "Unexpected WaveMesh access shadow scheduled sync error: "
                "key_id=%s reason=%s",
                key_id,
                reason,
            )

    _schedule(
        runner(),
        name=f"access-shadow-key-{key_id}",
    )


def schedule_access_shadow_backfill() -> None:
    if not access_shadow_sync_enabled() or not internal_api_client.configured:
        return
    _schedule(
        run_access_shadow_backfill(),
        name="access-shadow-startup-backfill",
    )
