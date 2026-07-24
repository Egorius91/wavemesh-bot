from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.services.access_shadow import AccessShadowSnapshot
from bot.services import access_shadow_reconciliation as reconciliation


class AccessShadowReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = AccessShadowSnapshot(
            telegram_id=123,
            legacy_key_id=7,
            username="user",
            display_name="User",
            is_bot_blocked=False,
            expires_at="2026-08-01T00:00:00.000Z",
            enabled=True,
            configured=True,
            subscription_ready=True,
            device_limit=2,
            traffic_limit_bytes="1000",
            traffic_used_bytes="100",
        )

    def test_dashboard_accesses_normalizes_values(self) -> None:
        result = reconciliation._dashboard_accesses(
            {
                "accesses": [
                    {
                        "legacy_key_id": "7",
                        "telegram_id": "123",
                        "expires_at": "2026-08-01T00:00:00.000Z",
                        "enabled": True,
                        "configured": True,
                        "subscription_ready": True,
                        "device_limit": 2,
                        "traffic_limit_bytes": 1000,
                        "traffic_used_bytes": 100,
                    }
                ]
            }
        )
        self.assertEqual(result[7], self.snapshot.access_payload())

    def test_matching_snapshot_is_not_synced(self) -> None:
        with (
            patch.object(
                reconciliation.internal_api_client,
                "get_telegram_dashboard",
                new=AsyncMock(
                    return_value={"accesses": [self.snapshot.access_payload()]}
                ),
            ),
            patch.object(
                reconciliation,
                "sync_access_shadow_snapshot",
                new=AsyncMock(),
            ) as sync,
        ):
            stats = asyncio.run(
                reconciliation._reconcile_user(
                    123,
                    [self.snapshot],
                    semaphore=asyncio.Semaphore(1),
                )
            )

        self.assertEqual(stats["checked"], 1)
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["repaired"], 0)
        sync.assert_not_awaited()

    def test_missing_snapshot_is_created(self) -> None:
        with (
            patch.object(
                reconciliation.internal_api_client,
                "get_telegram_dashboard",
                new=AsyncMock(return_value={"accesses": []}),
            ),
            patch.object(
                reconciliation,
                "sync_access_shadow_snapshot",
                new=AsyncMock(return_value={"created": True}),
            ) as sync,
        ):
            stats = asyncio.run(
                reconciliation._reconcile_user(
                    123,
                    [self.snapshot],
                    semaphore=asyncio.Semaphore(1),
                )
            )

        self.assertEqual(stats["checked"], 1)
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["repaired"], 1)
        sync.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
