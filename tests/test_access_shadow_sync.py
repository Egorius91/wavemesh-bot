import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from database import connection
from bot.services import access_shadow


class AccessShadowDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db_path = connection.DB_PATH
        connection.DB_PATH = Path(self.tmp.name) / "test.db"
        self._create_schema()

    def tearDown(self):
        connection.DB_PATH = self.old_db_path
        self.tmp.cleanup()

    def _create_schema(self):
        conn = sqlite3.connect(connection.DB_PATH)
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_bot_blocked INTEGER DEFAULT 0
            );
            CREATE TABLE tariffs (
                id INTEGER PRIMARY KEY,
                max_ips INTEGER DEFAULT 1
            );
            CREATE TABLE vpn_keys (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                server_id INTEGER,
                tariff_id INTEGER,
                panel_inbound_id INTEGER,
                client_uuid TEXT,
                panel_email TEXT,
                sub_id TEXT,
                expires_at DATETIME,
                traffic_limit INTEGER DEFAULT 0,
                traffic_used INTEGER DEFAULT 0
            );
            """
        )
        conn.execute(
            "INSERT INTO users VALUES (1, 127489706, 'egor', 'Egor', 'Sorkin', 0)"
        )
        conn.execute("INSERT INTO tariffs VALUES (1, 0)")
        conn.execute(
            """
            INSERT INTO vpn_keys (
                id, user_id, server_id, tariff_id, panel_inbound_id,
                client_uuid, panel_email, sub_id, expires_at,
                traffic_limit, traffic_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                3,
                1,
                7,
                1,
                11,
                "SENSITIVE-UUID",
                "SENSITIVE-PANEL-EMAIL",
                "SENSITIVE-SUB-ID",
                "2099-01-01 00:00:00",
                0,
                123,
            ),
        )
        conn.commit()
        conn.close()

    def test_snapshot_normalizes_and_excludes_runtime_credentials(self):
        snapshot = access_shadow.get_access_shadow_snapshot(3)

        self.assertIsNotNone(snapshot)
        payload = snapshot.access_payload()
        self.assertEqual(payload["telegram_id"], "127489706")
        self.assertEqual(payload["legacy_key_id"], "3")
        self.assertEqual(payload["device_limit"], 1)
        self.assertTrue(payload["configured"])
        self.assertTrue(payload["subscription_ready"])
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["traffic_limit_bytes"], "0")
        self.assertEqual(payload["traffic_used_bytes"], "123")

        serialized = repr(payload)
        self.assertNotIn("SENSITIVE-UUID", serialized)
        self.assertNotIn("SENSITIVE-PANEL-EMAIL", serialized)
        self.assertNotIn("SENSITIVE-SUB-ID", serialized)
        self.assertNotIn("client_uuid", payload)
        self.assertNotIn("panel_email", payload)
        self.assertNotIn("sub_id", payload)

    def test_traffic_exhaustion_disables_projection(self):
        conn = sqlite3.connect(connection.DB_PATH)
        conn.execute(
            "UPDATE vpn_keys SET traffic_limit = 100, traffic_used = 100 WHERE id = 3"
        )
        conn.commit()
        conn.close()

        snapshot = access_shadow.get_access_shadow_snapshot(3)
        self.assertFalse(snapshot.enabled)


class AccessShadowSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"WAVEMESH_ACCESS_SHADOW_SYNC_ENABLED": "true"},
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    async def test_sync_upserts_owner_before_access_with_stable_keys(self):
        snapshot = access_shadow.AccessShadowSnapshot(
            telegram_id=127489706,
            legacy_key_id=3,
            username="egor",
            display_name="Egor Sorkin",
            is_bot_blocked=False,
            expires_at="2099-01-01T00:00:00.000Z",
            enabled=True,
            configured=True,
            subscription_ready=True,
            device_limit=1,
            traffic_limit_bytes="0",
            traffic_used_bytes="123",
        )

        with (
            patch.object(
                access_shadow.internal_api_client,
                "upsert_telegram_user",
                new=AsyncMock(return_value={"user_id": "u1"}),
            ) as upsert_user,
            patch.object(
                access_shadow.internal_api_client,
                "sync_access_shadow",
                new=AsyncMock(
                    return_value={
                        "access_id": "wmb_test",
                        "status": "ready",
                        "created": True,
                        "desired_version": 1,
                    }
                ),
            ) as sync_access,
        ):
            first = await access_shadow.sync_access_shadow_snapshot(
                snapshot,
                reason="test",
            )
            second = await access_shadow.sync_access_shadow_snapshot(
                snapshot,
                reason="test",
            )

        self.assertEqual(first["access_id"], "wmb_test")
        self.assertEqual(second["access_id"], "wmb_test")
        self.assertEqual(upsert_user.await_count, 2)
        self.assertEqual(sync_access.await_count, 2)
        self.assertEqual(
            upsert_user.await_args_list[0].kwargs["idempotency_key"],
            upsert_user.await_args_list[1].kwargs["idempotency_key"],
        )
        self.assertEqual(
            sync_access.await_args_list[0].kwargs["idempotency_key"],
            sync_access.await_args_list[1].kwargs["idempotency_key"],
        )
        self.assertNotIn(
            "SENSITIVE",
            repr(sync_access.await_args_list[0].kwargs["payload"]),
        )

    async def test_backfill_is_noop_when_gate_is_disabled(self):
        with patch.dict(
            os.environ,
            {"WAVEMESH_ACCESS_SHADOW_SYNC_ENABLED": "false"},
            clear=False,
        ):
            result = await access_shadow.run_access_shadow_backfill()

        self.assertEqual(result, {"selected": 0, "synced": 0, "failed": 0})


if __name__ == "__main__":
    unittest.main()
