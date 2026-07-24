"""Startup reconciliation between SQLite access snapshots and WaveMesh SaaS."""

from __future__ import annotations

import asyncio
import logging
import os
from time import monotonic
from typing import Any

from bot.services.access_shadow import (
    AccessShadowSnapshot,
    access_shadow_sync_enabled,
    list_access_shadow_snapshots,
    sync_access_shadow_snapshot,
)
from bot.services.internal_api import InternalApiError, internal_api_client

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 10
DEFAULT_PROGRESS_EVERY = 100
MAX_CONCURRENCY = 50


def _concurrency() -> int:
    raw = os.getenv(
        "WAVEMESH_ACCESS_SHADOW_RECONCILIATION_CONCURRENCY",
        str(DEFAULT_CONCURRENCY),
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_CONCURRENCY
    return min(MAX_CONCURRENCY, max(1, value))


def _progress_every() -> int:
    raw = os.getenv(
        "WAVEMESH_ACCESS_SHADOW_RECONCILIATION_PROGRESS_EVERY",
        str(DEFAULT_PROGRESS_EVERY),
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_PROGRESS_EVERY
    return max(1, value)


def _normalize_access_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Normalizes the SaaS access shape to AccessShadowSnapshot fields only."""
    return {
        "telegram_id": str(value.get("telegram_id", "")),
        "legacy_key_id": str(value.get("legacy_key_id", "")),
        "expires_at": value.get("expires_at"),
        "enabled": bool(value.get("enabled", False)),
        "configured": bool(value.get("configured", False)),
        "subscription_ready": bool(value.get("subscription_ready", False)),
        "device_limit": int(value.get("device_limit", 1) or 1),
        "traffic_limit_bytes": str(value.get("traffic_limit_bytes", "0")),
        "traffic_used_bytes": str(value.get("traffic_used_bytes", "0")),
    }


def _dashboard_accesses(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = payload.get("accesses")
    if not isinstance(raw, list):
        return {}

    result: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            key_id = int(item.get("legacy_key_id"))
        except (TypeError, ValueError):
            continue
        result[key_id] = _normalize_access_payload(item)
    return result


async def _reconcile_user(
    telegram_id: int,
    snapshots: list[AccessShadowSnapshot],
    *,
    semaphore: asyncio.Semaphore,
) -> dict[str, int]:
    stats = {
        "checked": 0,
        "matched": 0,
        "repaired": 0,
        "created": 0,
        "disabled": 0,
        "failed": 0,
    }

    async with semaphore:
        try:
            dashboard = await internal_api_client.get_telegram_dashboard(telegram_id)
            remote = _dashboard_accesses(dashboard)
        except InternalApiError as error:
            stats["failed"] += len(snapshots)
            logger.warning(
                "WaveMesh startup reconciliation dashboard read failed: "
                "telegram_id=%s keys=%s code=%s status=%s retryable=%s",
                telegram_id,
                len(snapshots),
                error.code,
                error.status,
                error.retryable,
            )
            return stats
        except Exception:
            stats["failed"] += len(snapshots)
            logger.exception(
                "Unexpected WaveMesh startup reconciliation dashboard error: "
                "telegram_id=%s keys=%s",
                telegram_id,
                len(snapshots),
            )
            return stats

        for snapshot in snapshots:
            stats["checked"] += 1
            desired = snapshot.access_payload()
            current = remote.get(snapshot.legacy_key_id)
            if current == desired:
                stats["matched"] += 1
                continue

            try:
                result = await sync_access_shadow_snapshot(
                    snapshot,
                    reason="startup_reconciliation",
                )
            except InternalApiError as error:
                stats["failed"] += 1
                logger.warning(
                    "WaveMesh startup reconciliation repair failed: "
                    "key_id=%s telegram_id=%s code=%s status=%s retryable=%s",
                    snapshot.legacy_key_id,
                    telegram_id,
                    error.code,
                    error.status,
                    error.retryable,
                )
                continue
            except Exception:
                stats["failed"] += 1
                logger.exception(
                    "Unexpected WaveMesh startup reconciliation repair error: "
                    "key_id=%s telegram_id=%s",
                    snapshot.legacy_key_id,
                    telegram_id,
                )
                continue

            stats["repaired"] += 1
            if current is None or bool(result.get("created")):
                stats["created"] += 1
            if not snapshot.enabled:
                stats["disabled"] += 1

    return stats


async def run_access_shadow_startup_reconciliation() -> dict[str, int | float]:
    started = monotonic()
    totals: dict[str, int | float] = {
        "checked": 0,
        "matched": 0,
        "repaired": 0,
        "created": 0,
        "disabled": 0,
        "failed": 0,
        "duration_seconds": 0.0,
    }

    if not access_shadow_sync_enabled() or not internal_api_client.configured:
        logger.info("WaveMesh startup reconciliation is disabled")
        return totals

    snapshots = list_access_shadow_snapshots(limit=500)
    by_user: dict[int, list[AccessShadowSnapshot]] = {}
    for snapshot in snapshots:
        by_user.setdefault(snapshot.telegram_id, []).append(snapshot)

    semaphore = asyncio.Semaphore(_concurrency())
    tasks = [
        asyncio.create_task(
            _reconcile_user(telegram_id, user_snapshots, semaphore=semaphore),
            name=f"access-shadow-reconcile-{telegram_id}",
        )
        for telegram_id, user_snapshots in by_user.items()
    ]

    processed = 0
    progress_every = _progress_every()
    for future in asyncio.as_completed(tasks):
        stats = await future
        for key in ("checked", "matched", "repaired", "created", "disabled", "failed"):
            totals[key] = int(totals[key]) + stats[key]
        processed += stats["checked"] + stats["failed"]
        if processed and processed % progress_every == 0:
            logger.info(
                "WaveMesh startup reconciliation progress: processed=%s total=%s",
                processed,
                len(snapshots),
            )

    totals["duration_seconds"] = round(monotonic() - started, 3)
    logger.info(
        "WaveMesh startup reconciliation completed: checked=%s matched=%s "
        "repaired=%s created=%s disabled=%s failed=%s duration=%ss",
        totals["checked"],
        totals["matched"],
        totals["repaired"],
        totals["created"],
        totals["disabled"],
        totals["failed"],
        totals["duration_seconds"],
    )
    return totals
