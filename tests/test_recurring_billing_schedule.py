import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from database import connection
from database import db_subscriptions as subscriptions


class RecurringBillingDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db_path = connection.DB_PATH
        connection.DB_PATH = os.path.join(self.tmp.name, 'test.db')
        self.now = datetime(2026, 1, 1, 12, 0, 0)
        self.period_end = datetime(2026, 1, 31, 12, 0, 0)
        self._create_base_schema()
        subscriptions.ensure_subscription_schema()

    def tearDown(self):
        connection.DB_PATH = self.old_db_path
        self.tmp.cleanup()

    def _create_base_schema(self):
        conn = sqlite3.connect(connection.DB_PATH)
        conn.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER NOT NULL
            );
            CREATE TABLE tariffs (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                duration_days INTEGER NOT NULL,
                price_cents INTEGER NOT NULL DEFAULT 0,
                price_stars INTEGER NOT NULL DEFAULT 0,
                price_rub INTEGER NOT NULL DEFAULT 0,
                traffic_limit_gb INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE vpn_keys (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                tariff_id INTEGER,
                expires_at DATETIME,
                traffic_limit INTEGER DEFAULT 0,
                traffic_used INTEGER DEFAULT 0,
                traffic_updated_at DATETIME,
                traffic_notified_pct INTEGER DEFAULT 100
            );
            CREATE TABLE payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tariff_id INTEGER,
                order_id TEXT UNIQUE,
                payment_type TEXT,
                vpn_key_id INTEGER,
                amount_cents INTEGER DEFAULT 0,
                amount_stars INTEGER DEFAULT 0,
                period_days INTEGER,
                status TEXT DEFAULT 'pending',
                paid_at DATETIME,
                yookassa_payment_id TEXT
            );
        """)
        conn.execute("INSERT INTO users (id, telegram_id) VALUES (1, 1001)")
        conn.execute(
            "INSERT INTO tariffs (id, name, duration_days, price_rub, traffic_limit_gb) "
            "VALUES (1, 'Month', 30, 199, 100)"
        )
        conn.execute(
            "INSERT INTO vpn_keys (id, user_id, tariff_id, expires_at) VALUES (1, 1, 1, ?)",
            (self.period_end.strftime('%Y-%m-%d %H:%M:%S'),),
        )
        conn.commit()
        conn.close()

    def _create_subscription(self):
        with patch.object(subscriptions, '_utc_now', return_value=self.now):
            return subscriptions.create_subscription(
                user_id=1,
                tariff_id=1,
                vpn_key_id=1,
                payment_method_id='pm-1',
                billing_period_days=30,
                initial_payment_id='initial-1',
            )

    def test_first_charge_is_fifteen_minutes_before_paid_expiry(self):
        subscription_id = self._create_subscription()
        sub = subscriptions.get_subscription_by_id(subscription_id)

        self.assertEqual(sub['period_end_at'], '2026-01-31 12:00:00')
        self.assertEqual(sub['next_charge_at'], '2026-01-31 11:45:00')
        self.assertEqual(sub['grace_until'], '2026-02-01 12:00:00')

    def test_retry_schedule_and_final_failure(self):
        subscription_id = self._create_subscription()
        failure_time = self.period_end - timedelta(minutes=15)

        with patch.object(subscriptions, '_utc_now', return_value=failure_time):
            first = subscriptions.record_subscription_payment_failure(subscription_id, reason='declined')
            second = subscriptions.record_subscription_payment_failure(subscription_id, reason='declined')
            third = subscriptions.record_subscription_payment_failure(subscription_id, reason='declined')
            fourth = subscriptions.record_subscription_payment_failure(subscription_id, reason='declined')

        self.assertEqual(first['next_charge_at'], '2026-01-31 13:00:00')
        self.assertEqual(second['next_charge_at'], '2026-01-31 18:00:00')
        self.assertEqual(third['next_charge_at'], '2026-02-01 12:00:00')
        self.assertFalse(first['final'])
        self.assertTrue(fourth['final'])
        self.assertEqual(fourth['status'], 'expired')
        self.assertEqual(subscriptions.get_subscription_by_id(subscription_id)['failed_attempts'], 4)

    def test_success_after_grace_uses_paid_anchor_not_grace_extension(self):
        subscription_id = self._create_subscription()
        grace_until = self.period_end + timedelta(hours=24)
        conn = sqlite3.connect(connection.DB_PATH)
        conn.execute(
            "UPDATE vpn_keys SET expires_at = ? WHERE id = 1",
            (grace_until.strftime('%Y-%m-%d %H:%M:%S'),),
        )
        conn.execute("""
            INSERT INTO payments (
                user_id, tariff_id, order_id, payment_type, vpn_key_id,
                period_days, status, subscription_id, is_recurring
            ) VALUES (1, 1, '001', 'yookassa_recurring', 1, 30, 'pending', ?, 1)
        """, (subscription_id,))
        conn.commit()
        conn.close()

        paid_at = self.period_end + timedelta(hours=2)
        with patch.object(subscriptions, '_utc_now', return_value=paid_at):
            result = subscriptions.finalize_recurring_payment(
                '001',
                subscription_id,
                payment_id='payment-2',
                payment_method_id='pm-1',
            )

        expected_end = paid_at + timedelta(days=30)
        self.assertTrue(result['processed_now'])
        self.assertEqual(result['period_end_at'], expected_end.strftime('%Y-%m-%d %H:%M:%S'))

        conn = sqlite3.connect(connection.DB_PATH)
        key_expiry = conn.execute("SELECT expires_at FROM vpn_keys WHERE id = 1").fetchone()[0]
        payment_status = conn.execute("SELECT status FROM payments WHERE order_id = '001'").fetchone()[0]
        conn.close()
        self.assertEqual(key_expiry, expected_end.strftime('%Y-%m-%d %H:%M:%S'))
        self.assertEqual(payment_status, 'paid')

    def test_payment_failed_subscription_remains_due_for_retry(self):
        subscription_id = self._create_subscription()
        conn = sqlite3.connect(connection.DB_PATH)
        conn.execute("""
            UPDATE subscriptions
            SET status = 'payment_failed', next_charge_at = '2020-01-01 00:00:00'
            WHERE id = ?
        """, (subscription_id,))
        conn.commit()
        conn.close()

        due = subscriptions.get_due_subscriptions()
        self.assertEqual([row['id'] for row in due], [subscription_id])


class RecurringBillingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_cycle_does_not_write_info_log(self):
        from bot.services import subscription_billing as billing

        with patch.object(billing, 'get_due_subscriptions', return_value=[]):
            with self.assertNoLogs(billing.logger, level='INFO'):
                result = await billing.process_due_subscriptions(AsyncMock())

        self.assertEqual(result['due'], 0)

    async def test_existing_pending_payment_is_polled_without_new_order(self):
        from bot.services import subscription_billing as billing

        subscription = {
            'id': 7,
            'user_id': 1,
            'tariff_id': 1,
            'vpn_key_id': 3,
            'price_rub': 199,
            'payment_method_id': 'pm-1',
            'billing_period_days': 30,
            'tariff_name': 'Month',
            'grace_until': '2099-01-01 00:00:00',
        }
        open_order = {'order_id': '009', 'yookassa_payment_id': 'pay-9'}

        with (
            patch.object(billing, 'get_open_recurring_order', return_value=open_order),
            patch.object(
                billing,
                'get_yookassa_payment',
                AsyncMock(return_value={'id': 'pay-9', 'status': 'pending'}),
            ),
            patch.object(billing, 'create_pending_order') as create_order,
            patch.object(billing, 'create_yookassa_recurring_payment', AsyncMock()) as create_payment,
            patch.object(billing, 'save_yookassa_payment_id'),
            patch.object(billing, 'save_order_subscription_context'),
            patch.object(billing, 'reschedule_subscription_check'),
            patch.object(billing, '_ensure_grace_access', AsyncMock()),
        ):
            result = await billing.process_due_subscription(subscription, AsyncMock())

        self.assertEqual(result['status'], 'pending')
        create_order.assert_not_called()
        create_payment.assert_not_awaited()

    async def test_network_error_keeps_pending_order_for_idempotent_retry(self):
        from bot.services import subscription_billing as billing

        subscription = {
            'id': 8,
            'user_id': 1,
            'tariff_id': 1,
            'vpn_key_id': 3,
            'price_rub': 199,
            'payment_method_id': 'pm-1',
            'billing_period_days': 30,
            'tariff_name': 'Month',
            'grace_until': '2099-01-01 00:00:00',
        }

        with (
            patch.object(billing, 'get_open_recurring_order', return_value=None),
            patch.object(billing, 'create_pending_order', return_value=(10, '00A')) as create_order,
            patch.object(billing, 'save_order_subscription_context'),
            patch.object(
                billing,
                'create_yookassa_recurring_payment',
                AsyncMock(side_effect=TimeoutError('timeout')),
            ),
            patch.object(billing, 'mark_subscription_transient_error') as transient,
            patch.object(billing, '_ensure_grace_access', AsyncMock()),
        ):
            result = await billing.process_due_subscription(subscription, AsyncMock())

        self.assertEqual(result['status'], 'transient')
        create_order.assert_called_once()
        transient.assert_called_once()

    async def test_success_uses_atomic_finalization(self):
        from bot.services import subscription_billing as billing

        subscription = {
            'id': 9,
            'user_id': 1,
            'tariff_id': 1,
            'vpn_key_id': 3,
            'price_rub': 199,
            'payment_method_id': 'pm-1',
            'billing_period_days': 30,
            'tariff_name': 'Month',
        }
        open_order = {'order_id': '00B', 'yookassa_payment_id': 'pay-10'}
        finalized = {
            'subscription_id': 9,
            'vpn_key_id': 3,
            'tariff_id': 1,
            'processed_now': True,
            'period_end_at': '2026-02-28 00:00:00',
            'grace_until': '2026-03-01 00:00:00',
            'next_charge_at': '2026-02-27 23:45:00',
        }

        with (
            patch.object(billing, 'get_open_recurring_order', return_value=open_order),
            patch.object(
                billing,
                'get_yookassa_payment',
                AsyncMock(return_value={'id': 'pay-10', 'status': 'succeeded'}),
            ),
            patch.object(billing, 'save_yookassa_payment_id'),
            patch.object(billing, 'save_order_subscription_context'),
            patch.object(billing, 'finalize_recurring_payment', return_value=finalized) as finalize,
            patch.object(billing, 'get_tariff_by_id', return_value={'traffic_limit_gb': 100}),
            patch.object(billing, 'update_vpn_key_tariff_and_traffic_limit'),
            patch.object(billing, '_sync_key_state', AsyncMock(return_value=True)),
            patch.object(billing, '_notify_payment_success', AsyncMock()),
        ):
            result = await billing.process_due_subscription(subscription, AsyncMock())

        self.assertEqual(result['status'], 'succeeded')
        finalize.assert_called_once_with(
            '00B',
            9,
            payment_id='pay-10',
            payment_method_id='pm-1',
        )


if __name__ == '__main__':
    unittest.main()
