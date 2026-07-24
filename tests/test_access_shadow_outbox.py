from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bot.services.access_shadow import AccessShadowSnapshot
from bot.services import access_shadow_outbox as outbox
from database import connection


class AccessShadowOutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.db"
        self.db_patch = patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        outbox.ensure_access_shadow_outbox_schema()
        self.snapshot = AccessShadowSnapshot(
            telegram_id=123,
            legacy_key_id=7,
            username="user",
            display_name="User",
            is_bot_blocked=False,
            expires_at="2026-08-01T00:00:00.000Z",
            enabled=False,
            configured=False,
            subscription_ready=False,
            device_limit=2,
            traffic_limit_bytes="1000",
            traffic_used_bytes="100",
        )

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_enqueue_is_durable_and_idempotent(self) -> None:
        self.assertTrue(outbox.enqueue_access_shadow_snapshot(self.snapshot, reason="delete"))
        self.assertFalse(outbox.enqueue_access_shadow_snapshot(self.snapshot, reason="delete"))
        self.assertEqual(outbox.pending_access_shadow_outbox_count(), 1)

        # A fresh SQLite connection sees the committed event.
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM access_shadow_outbox").fetchone()[0]
        self.assertEqual(count, 1)

    def test_successful_delivery_removes_event(self) -> None:
        outbox.enqueue_access_shadow_snapshot(self.snapshot, reason="delete")
        with (
            patch.object(outbox.internal_api_client, "configured", True),
            patch.object(
                outbox,
                "sync_access_shadow_snapshot",
                new=AsyncMock(return_value={"status": "disabled"}),
            ) as sync,
        ):
            stats = asyncio.run(outbox.drain_access_shadow_outbox_once())

        self.assertEqual(stats, {"selected": 1, "delivered": 1, "failed": 0})
        self.assertEqual(outbox.pending_access_shadow_outbox_count(), 0)
        delivered = sync.await_args.args[0]
        self.assertEqual(delivered.legacy_key_id, 7)
        self.assertFalse(delivered.enabled)
        self.assertEqual(sync.await_args.kwargs["reason"], "outbox_delete")

    def test_failure_keeps_event_and_increments_attempts(self) -> None:
        outbox.enqueue_access_shadow_snapshot(self.snapshot, reason="delete")
        with (
            patch.object(outbox.internal_api_client, "configured", True),
            patch.object(
                outbox,
                "sync_access_shadow_snapshot",
                new=AsyncMock(side_effect=RuntimeError("offline")),
            ),
        ):
            stats = asyncio.run(outbox.drain_access_shadow_outbox_once())

        self.assertEqual(stats, {"selected": 1, "delivered": 0, "failed": 1})
        self.assertEqual(outbox.pending_access_shadow_outbox_count(), 1)
        with connection.get_db() as conn:
            row = conn.execute(
                "SELECT attempts, last_error FROM access_shadow_outbox"
            ).fetchone()
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["last_error"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
