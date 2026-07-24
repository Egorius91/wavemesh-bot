from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import connection
from database.access_shadow_outbox_triggers import ensure_access_shadow_outbox_triggers


class AccessShadowOutboxTriggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.db"
        self.db_patch = patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        with connection.get_db() as conn:
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
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    server_id INTEGER,
                    tariff_id INTEGER,
                    panel_email TEXT,
                    client_uuid TEXT,
                    sub_id TEXT,
                    expires_at TEXT,
                    traffic_limit INTEGER DEFAULT 0,
                    traffic_used INTEGER DEFAULT 0
                );
                INSERT INTO users
                    (id, telegram_id, username, first_name, last_name, is_bot_blocked)
                VALUES (1, 123, 'alice', 'Alice', 'Example', 0);
                INSERT INTO tariffs (id, max_ips) VALUES (2, 3);
                """
            )
        ensure_access_shadow_outbox_triggers()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_insert_and_update_are_captured_transactionally(self) -> None:
        with connection.get_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO vpn_keys
                    (user_id, server_id, tariff_id, panel_email, client_uuid,
                     sub_id, expires_at, traffic_limit, traffic_used)
                VALUES (1, 4, 2, 'panel@example.test', 'uuid', 'sub',
                        '2026-08-01 00:00:00', 1000, 100)
                """
            )
            key_id = int(cursor.lastrowid)

        with connection.get_db() as conn:
            insert_event = conn.execute(
                "SELECT reason, payload_json FROM access_shadow_outbox ORDER BY id LIMIT 1"
            ).fetchone()
        self.assertEqual(insert_event["reason"], "mutation_insert")
        self.assertIn('"legacy_key_id":1', insert_event["payload_json"])
        self.assertIn('"device_limit":3', insert_event["payload_json"])

        with connection.get_db() as conn:
            conn.execute(
                "UPDATE vpn_keys SET traffic_used = ? WHERE id = ?",
                (250, key_id),
            )

        with connection.get_db() as conn:
            reasons = [
                row["reason"]
                for row in conn.execute(
                    "SELECT reason FROM access_shadow_outbox ORDER BY id"
                ).fetchall()
            ]
        self.assertEqual(reasons, ["mutation_insert", "mutation_update"])

    def test_rollback_does_not_leave_outbox_event(self) -> None:
        conn = connection.get_connection()
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO vpn_keys
                    (user_id, tariff_id, expires_at, traffic_limit, traffic_used)
                VALUES (1, 2, '2026-08-01 00:00:00', 0, 0)
                """
            )
            conn.rollback()
        finally:
            conn.close()

        with connection.get_db() as check:
            count = check.execute(
                "SELECT COUNT(*) AS count FROM access_shadow_outbox"
            ).fetchone()["count"]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
