"""Reconcile expired subscription keys with VPN panel state.

3X-UI enforces ``expiryTime`` itself, but the bot must also materialize the
expired state by setting every client in a native subscription to
``enable=False``. The regular traffic synchronizer only loads active keys, so
expired keys need a small dedicated reconciliation pass.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

# Avoid polling the panel for the same expired key every five minutes. The set
# is intentionally process-local: after a restart every expired key is checked
# once again, which repairs any drift that happened while the bot was offline.
_reconciled_expired_ids: set[int] = set()


def _key_ids(keys: Iterable[Mapping[str, Any]]) -> set[int]:
    result: set[int] = set()
    for key in keys:
        try:
            result.add(int(key["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _expired_subscription_ids(
    active_keys: Iterable[Mapping[str, Any]],
    all_keys: Iterable[Mapping[str, Any]],
) -> set[int]:
    """Return subscription key IDs that are no longer in the active query."""
    active_ids = _key_ids(active_keys)
    expired_ids: set[int] = set()

    for key in all_keys:
        if not key.get("sub_id"):
            continue
        try:
            key_id = int(key["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if key_id not in active_ids:
            expired_ids.add(key_id)

    return expired_ids


async def reconcile_expired_subscription_keys() -> dict[str, int]:
    """Disable newly expired native-subscription clients on their panels.

    Successful keys are remembered until they become active again. Failed keys
    are left pending and retried on the next pass.
    """
    from database.db_keys import (
        get_all_active_keys_with_server,
        get_all_keys_with_server,
    )
    from bot.services.vpn_api import (
        ensure_subscription_keys_on_server,
        is_subscription_mode,
    )

    stats = {
        "expired": 0,
        "processed": 0,
        "disabled": 0,
        "errors": 0,
        "skipped": 0,
    }

    if not is_subscription_mode():
        _reconciled_expired_ids.clear()
        return stats

    active_keys = get_all_active_keys_with_server()
    all_keys = get_all_keys_with_server()
    expired_ids = _expired_subscription_ids(active_keys, all_keys)
    stats["expired"] = len(expired_ids)

    # An extended or replaced key must be eligible for reconciliation after its
    # next expiration.
    _reconciled_expired_ids.intersection_update(expired_ids)

    pending_ids = sorted(expired_ids - _reconciled_expired_ids)
    stats["skipped"] = len(expired_ids) - len(pending_ids)

    for key_id in pending_ids:
        try:
            result = await ensure_subscription_keys_on_server(key_id)
            errors = int(result.get("errors", 0) or 0)
            if errors:
                stats["errors"] += errors
                logger.warning(
                    "Expired subscription key %s was not fully reconciled: %s",
                    key_id,
                    result,
                )
                continue

            _reconciled_expired_ids.add(key_id)
            stats["processed"] += 1
            stats["disabled"] += int(result.get("disabled", 0) or 0)
        except Exception as exc:
            stats["errors"] += 1
            logger.warning(
                "Failed to reconcile expired subscription key %s: %s",
                key_id,
                exc,
            )

    if stats["processed"] or stats["errors"]:
        logger.info("Expired subscription reconciliation finished: %s", stats)

    return stats


async def run_expired_key_reconciler(
    *,
    interval_seconds: int = 300,
    initial_delay_seconds: int = 30,
) -> None:
    """Run expired-key reconciliation periodically until cancelled."""
    interval_seconds = max(1, int(interval_seconds))
    initial_delay_seconds = max(0, int(initial_delay_seconds))

    if initial_delay_seconds:
        await asyncio.sleep(initial_delay_seconds)

    logger.info(
        "Expired subscription reconciler started (interval=%ss)",
        interval_seconds,
    )

    while True:
        try:
            await reconcile_expired_subscription_keys()
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Expired subscription reconciler stopped")
            raise
        except Exception as exc:
            logger.error("Expired subscription reconciler failed: %s", exc)
            await asyncio.sleep(min(interval_seconds, 120))
