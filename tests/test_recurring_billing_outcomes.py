import unittest
from unittest.mock import AsyncMock, patch

from bot.services import subscription_billing as billing


class RecurringBillingOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_definitive_failure_reports_billing_outcome_not_db_status(self):
        subscription = {'id': 12, 'vpn_key_id': 3, 'user_telegram_id': 1001}
        stored_failure = {
            'subscription_id': 12,
            'failed_attempts': 1,
            'final': False,
            'status': 'payment_failed',
            'period_end_at': '2026-01-31 12:00:00',
            'grace_until': '2026-02-01 12:00:00',
            'next_charge_at': '2026-01-31 13:00:00',
        }

        with (
            patch.object(billing, 'fail_order'),
            patch.object(
                billing,
                'record_subscription_payment_failure',
                return_value=stored_failure,
            ),
            patch.object(billing, '_apply_failure_access', AsyncMock()),
            patch.object(billing, '_notify_payment_failed', AsyncMock()),
        ):
            result = await billing._record_definitive_failure(
                subscription,
                '00C',
                AsyncMock(),
                reason='declined',
            )

        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_attempts'], 1)
        self.assertEqual(result['subscription_id'], 12)


if __name__ == '__main__':
    unittest.main()
