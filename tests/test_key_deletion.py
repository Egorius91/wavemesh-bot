import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from database import connection
from database.db_keys import delete_vpn_key


class KeyDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = connection.DB_PATH
        connection.DB_PATH = Path(self.temp_dir.name) / "test.db"

        with closing(sqlite3.connect(connection.DB_PATH)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript("""
                CREATE TABLE vpn_keys (
                    id INTEGER PRIMARY KEY
                );
                CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY,
                    vpn_key_id INTEGER,
                    status TEXT NOT NULL,
                    payment_method_id TEXT,
                    cancel_at_period_end INTEGER DEFAULT 0,
                    cancelled_at DATETIME,
                    FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id)
                );
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY,
                    vpn_key_id INTEGER,
                    subscription_id INTEGER,
                    payment_method_id TEXT,
                    FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id),
                    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
                );
                CREATE TABLE notification_log (
                    id INTEGER PRIMARY KEY,
                    vpn_key_id INTEGER NOT NULL,
                    FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id)
                );
            """)
            conn.executemany("INSERT INTO vpn_keys(id) VALUES (?)", [(1,), (2,)])
            conn.executemany(
                """
                INSERT INTO subscriptions(
                    id, vpn_key_id, status, payment_method_id,
                    cancel_at_period_end
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (10, 1, "active", "saved-method", 0),
                    (20, 2, "active", "other-method", 0),
                ],
            )
            conn.executemany(
                """
                INSERT INTO payments(
                    id, vpn_key_id, subscription_id, payment_method_id
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (100, 1, 10, "saved-method"),
                    (200, 2, 20, "other-method"),
                ],
            )
            conn.execute(
                "INSERT INTO notification_log(id, vpn_key_id) VALUES (1, 1)"
            )
            conn.commit()

    def tearDown(self):
        connection.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_delete_key_cancels_subscription_and_preserves_history(self):
        self.assertTrue(delete_vpn_key(1))

        with closing(sqlite3.connect(connection.DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertIsNone(
                conn.execute("SELECT id FROM vpn_keys WHERE id = 1").fetchone()
            )
            subscription = conn.execute(
                "SELECT * FROM subscriptions WHERE id = 10"
            ).fetchone()
            self.assertEqual(subscription["status"], "cancelled")
            self.assertIsNone(subscription["vpn_key_id"])
            self.assertIsNone(subscription["payment_method_id"])
            self.assertEqual(subscription["cancel_at_period_end"], 1)
            self.assertIsNotNone(subscription["cancelled_at"])

            payment = conn.execute(
                "SELECT * FROM payments WHERE id = 100"
            ).fetchone()
            self.assertIsNone(payment["vpn_key_id"])
            self.assertIsNone(payment["payment_method_id"])
            self.assertIsNone(
                conn.execute("SELECT id FROM notification_log").fetchone()
            )

            untouched = conn.execute(
                "SELECT * FROM subscriptions WHERE id = 20"
            ).fetchone()
            self.assertEqual(untouched["status"], "active")
            self.assertEqual(untouched["vpn_key_id"], 2)
            self.assertEqual(untouched["payment_method_id"], "other-method")


if __name__ == "__main__":
    unittest.main()
