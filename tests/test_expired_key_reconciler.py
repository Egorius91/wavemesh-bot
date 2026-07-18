import unittest
from unittest.mock import AsyncMock, patch

from bot.services import expired_key_reconciler as reconciler


class ExpiredSubscriptionReconcilerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reconciler._reconciled_expired_ids.clear()

    async def test_disables_subscription_key_missing_from_active_query(self):
        ensure = AsyncMock(return_value={"disabled": 3, "errors": 0, "ok": 1})

        with (
            patch("bot.services.vpn_api.is_subscription_mode", return_value=True),
            patch(
                "database.db_keys.get_all_active_keys_with_server",
                return_value=[{"id": 1, "sub_id": "active-sub"}],
            ),
            patch(
                "database.db_keys.get_all_keys_with_server",
                return_value=[
                    {"id": 1, "sub_id": "active-sub"},
                    {"id": 2, "sub_id": "expired-sub"},
                    {"id": 3, "sub_id": None},
                ],
            ),
            patch(
                "bot.services.vpn_api.ensure_subscription_keys_on_server",
                ensure,
            ),
        ):
            result = await reconciler.reconcile_expired_subscription_keys()

        ensure.assert_awaited_once_with(2)
        self.assertEqual(result["expired"], 1)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["disabled"], 3)
        self.assertEqual(result["errors"], 0)

    async def test_successful_key_is_not_repolled_every_cycle(self):
        ensure = AsyncMock(return_value={"disabled": 1, "errors": 0, "ok": 1})

        with (
            patch("bot.services.vpn_api.is_subscription_mode", return_value=True),
            patch(
                "database.db_keys.get_all_active_keys_with_server",
                return_value=[],
            ),
            patch(
                "database.db_keys.get_all_keys_with_server",
                return_value=[{"id": 2, "sub_id": "expired-sub"}],
            ),
            patch(
                "bot.services.vpn_api.ensure_subscription_keys_on_server",
                ensure,
            ),
        ):
            first = await reconciler.reconcile_expired_subscription_keys()
            second = await reconciler.reconcile_expired_subscription_keys()

        ensure.assert_awaited_once_with(2)
        self.assertEqual(first["processed"], 1)
        self.assertEqual(second["processed"], 0)
        self.assertEqual(second["skipped"], 1)

    async def test_extended_key_can_be_reconciled_after_next_expiration(self):
        ensure = AsyncMock(return_value={"disabled": 1, "errors": 0, "ok": 1})
        active_query = unittest.mock.Mock(
            side_effect=[
                [],
                [{"id": 2, "sub_id": "subscription"}],
                [],
            ]
        )

        with (
            patch("bot.services.vpn_api.is_subscription_mode", return_value=True),
            patch(
                "database.db_keys.get_all_active_keys_with_server",
                active_query,
            ),
            patch(
                "database.db_keys.get_all_keys_with_server",
                return_value=[{"id": 2, "sub_id": "subscription"}],
            ),
            patch(
                "bot.services.vpn_api.ensure_subscription_keys_on_server",
                ensure,
            ),
        ):
            await reconciler.reconcile_expired_subscription_keys()
            await reconciler.reconcile_expired_subscription_keys()
            await reconciler.reconcile_expired_subscription_keys()

        self.assertEqual(ensure.await_count, 2)
        self.assertEqual(ensure.await_args_list[0].args, (2,))
        self.assertEqual(ensure.await_args_list[1].args, (2,))

    async def test_failed_reconciliation_is_retried(self):
        ensure = AsyncMock(
            side_effect=[
                {"disabled": 0, "errors": 1, "ok": 0},
                {"disabled": 1, "errors": 0, "ok": 1},
            ]
        )

        with (
            patch("bot.services.vpn_api.is_subscription_mode", return_value=True),
            patch(
                "database.db_keys.get_all_active_keys_with_server",
                return_value=[],
            ),
            patch(
                "database.db_keys.get_all_keys_with_server",
                return_value=[{"id": 2, "sub_id": "expired-sub"}],
            ),
            patch(
                "bot.services.vpn_api.ensure_subscription_keys_on_server",
                ensure,
            ),
        ):
            first = await reconciler.reconcile_expired_subscription_keys()
            second = await reconciler.reconcile_expired_subscription_keys()

        self.assertEqual(ensure.await_count, 2)
        self.assertEqual(first["errors"], 1)
        self.assertEqual(second["processed"], 1)


if __name__ == "__main__":
    unittest.main()
