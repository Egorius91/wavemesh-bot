import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.user.payments import payment_return
from bot.handlers.user.payments.payment_return import (
    _local_projection_needs_refresh,
    extract_payment_return_payload,
    PaymentReturnMaterialization,
    VerifiedReadyPaymentReturn,
    materialize_ready_payment_return,
    payment_return_status_text,
    process_ready_payment_return,
)
from bot.services.internal_api import InternalApiError
from database.payment_return_projection import refresh_materialized_key_from_saas


TOKEN = "pay_" + "A" * 32
ACCESS_ID = "access-12345678"
TELEGRAM_ID = 123456789
USER_ID = 42
LOCAL_TARIFF_ID = 7
REMOTE_TARIFF_ID = "tariff-12345678"
EXPIRY = "2026-09-01 12:30:00"
TRAFFIC_LIMIT = 1024


def ready_access(*, legacy_key_id=None, expires_at=EXPIRY):
    return {
        "access_id": ACCESS_ID,
        "status": "ready",
        "tariff_id": REMOTE_TARIFF_ID,
        "expires_at": expires_at,
        "traffic_limit_bytes": str(TRAFFIC_LIMIT),
        "legacy_key_id": legacy_key_id,
    }


def ready_material():
    return {
        "access_id": ACCESS_ID,
        "status": "ready",
        "ready": True,
        "desired_version": 1,
        "panel_email": "wm_access_123",
        "client_uuid": "f5ee70ce-8a27-4f15-b81e-edc8a8bd11c4",
        "sub_id": "abcdefghijklmnop",
        "primary_inbound_id": 9,
        "protocol": "vless",
        "subscription_url": "https://entry.example.invalid/sub/value",
    }


def local_key(*, key_id=55, expires_at=EXPIRY, tariff_id=LOCAL_TARIFF_ID):
    return {
        "id": key_id,
        "user_id": USER_ID,
        "tariff_id": tariff_id,
        "expires_at": expires_at,
        "traffic_limit": TRAFFIC_LIMIT,
        "panel_email": "wm_access_123",
        "client_uuid": "f5ee70ce-8a27-4f15-b81e-edc8a8bd11c4",
        "sub_id": "abcdefghijklmnop",
    }


class PaymentReturnPureTests(unittest.TestCase):
    def test_extracts_only_exact_payment_return_start_payload(self):
        self.assertEqual(
            extract_payment_return_payload(f"/start {TOKEN}"),
            TOKEN,
        )
        self.assertEqual(
            extract_payment_return_payload(f"/start@wavemeshtest_bot {TOKEN}"),
            TOKEN,
        )
        self.assertIsNone(extract_payment_return_payload(TOKEN))
        self.assertIsNone(extract_payment_return_payload(f"/start {TOKEN} extra"))
        self.assertIsNone(extract_payment_return_payload("/start pay_too-short"))
        self.assertIsNone(extract_payment_return_payload(None))

    def test_verified_status_copy_never_reflects_token(self):
        for status in (
            "pending",
            "cancelled",
            "access_creating",
            "support_error",
        ):
            with self.subTest(status=status):
                text = payment_return_status_text(status)
                self.assertTrue(text)
                self.assertNotIn(TOKEN, text)

        with self.assertRaises(InternalApiError):
            payment_return_status_text("ready")

    def test_projection_refresh_compares_all_commercial_fields(self):
        current = local_key()
        self.assertFalse(
            _local_projection_needs_refresh(
                current,
                tariff_id=LOCAL_TARIFF_ID,
                expires_at=EXPIRY,
                traffic_limit=TRAFFIC_LIMIT,
            )
        )
        self.assertTrue(
            _local_projection_needs_refresh(
                current,
                tariff_id=LOCAL_TARIFF_ID + 1,
                expires_at=EXPIRY,
                traffic_limit=TRAFFIC_LIMIT,
            )
        )
        self.assertTrue(
            _local_projection_needs_refresh(
                current,
                tariff_id=LOCAL_TARIFF_ID,
                expires_at="2026-10-01 12:30:00",
                traffic_limit=TRAFFIC_LIMIT,
            )
        )
        self.assertTrue(
            _local_projection_needs_refresh(
                current,
                tariff_id=LOCAL_TARIFF_ID,
                expires_at=EXPIRY,
                traffic_limit=TRAFFIC_LIMIT + 1,
            )
        )

    def test_atomic_projection_refresh_updates_one_row(self):
        cursor = MagicMock(rowcount=1)
        connection = MagicMock()
        connection.execute.return_value = cursor

        @contextmanager
        def fake_db():
            yield connection

        with patch(
            "database.payment_return_projection.get_db",
            side_effect=fake_db,
        ):
            result = refresh_materialized_key_from_saas(
                key_id=55,
                tariff_id=LOCAL_TARIFF_ID,
                expires_at=EXPIRY,
                traffic_limit=TRAFFIC_LIMIT,
            )

        self.assertTrue(result)
        sql, parameters = connection.execute.call_args.args
        self.assertIn("UPDATE vpn_keys", sql)
        self.assertIn("traffic_used = 0", sql)
        self.assertEqual(
            parameters,
            (LOCAL_TARIFF_ID, EXPIRY, TRAFFIC_LIMIT, 55),
        )


class PaymentReturnMaterializationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        payment_return._ACCESS_LOCKS.clear()

    @contextmanager
    def _mock_api(self, access):
        dashboard_mock = AsyncMock(return_value={"accesses": [access]})
        material_mock = AsyncMock(return_value=ready_material())
        tariffs_mock = AsyncMock(
            return_value=[
                {
                    "tariff_id": REMOTE_TARIFF_ID,
                    "duration_days": 30,
                    "price_rub": 299,
                    "device_limit": 1,
                    "traffic_limit_gb": 0,
                }
            ]
        )
        link_mock = AsyncMock(
            return_value={
                "access_id": ACCESS_ID,
                "legacy_key_id": "55",
            }
        )

        with (
            patch.object(
                payment_return.internal_api_client,
                "get_telegram_dashboard",
                dashboard_mock,
            ),
            patch.object(
                payment_return.internal_api_client,
                "get_access_material",
                material_mock,
            ),
            patch.object(
                payment_return.internal_api_client,
                "list_tariffs",
                tariffs_mock,
            ),
            patch.object(
                payment_return.internal_api_client,
                "link_access_projection",
                link_mock,
            ),
        ):
            yield link_mock

    async def test_repeated_ready_return_reuses_existing_projection(self):
        existing = local_key()
        final_key = {**existing, "display_name": "abcd...mnop"}

        with (
            self._mock_api(ready_access()) as link_mock,
            patch(
                "bot.handlers.user.payments.saas._resolve_local_projection_tariffs",
                return_value=[{"id": LOCAL_TARIFF_ID}],
            ),
            patch("database.requests.get_user_internal_id", return_value=USER_ID),
            patch("database.requests.get_all_tariffs", return_value=[{"id": LOCAL_TARIFF_ID}]),
            patch("database.requests.get_key_details_for_user", return_value=final_key),
            patch(
                "database.db_keys.find_materialized_key_for_user",
                return_value=existing,
            ),
            patch("database.db_keys.create_materialized_vpn_key_from_saas") as create_key,
            patch("database.payment_return_projection.refresh_materialized_key_from_saas") as refresh_key,
            patch("database.requests.get_active_servers") as get_servers,
            patch.object(
                payment_return,
                "_local_key_from_declared_projection",
                return_value=None,
            ),
        ):
            result = await materialize_ready_payment_return(
                telegram_id=TELEGRAM_ID,
                access_id=ACCESS_ID,
            )

        self.assertEqual(result.outcome, "existing")
        self.assertEqual(result.key_id, 55)
        create_key.assert_not_called()
        refresh_key.assert_not_called()
        get_servers.assert_not_called()
        link_mock.assert_awaited_once_with(
            access_id=ACCESS_ID,
            telegram_id=TELEGRAM_ID,
            legacy_key_id=55,
            idempotency_key=f"paid-access-projection-{ACCESS_ID}-55",
        )

    async def test_ready_renewal_refreshes_existing_projection_once(self):
        existing = local_key(expires_at="2026-08-01 12:30:00")
        final_key = local_key()

        with (
            self._mock_api(ready_access()),
            patch(
                "bot.handlers.user.payments.saas._resolve_local_projection_tariffs",
                return_value=[{"id": LOCAL_TARIFF_ID}],
            ),
            patch("database.requests.get_user_internal_id", return_value=USER_ID),
            patch("database.requests.get_all_tariffs", return_value=[{"id": LOCAL_TARIFF_ID}]),
            patch("database.requests.get_key_details_for_user", return_value=final_key),
            patch(
                "database.db_keys.find_materialized_key_for_user",
                return_value=existing,
            ),
            patch("database.db_keys.create_materialized_vpn_key_from_saas") as create_key,
            patch(
                "database.payment_return_projection.refresh_materialized_key_from_saas",
                return_value=True,
            ) as refresh_key,
            patch("database.requests.get_active_servers") as get_servers,
            patch.object(
                payment_return,
                "_local_key_from_declared_projection",
                return_value=None,
            ),
        ):
            result = await materialize_ready_payment_return(
                telegram_id=TELEGRAM_ID,
                access_id=ACCESS_ID,
            )

        self.assertEqual(result.outcome, "renewed")
        create_key.assert_not_called()
        get_servers.assert_not_called()
        refresh_key.assert_called_once_with(
            key_id=55,
            tariff_id=LOCAL_TARIFF_ID,
            expires_at=EXPIRY,
            traffic_limit=TRAFFIC_LIMIT,
        )

    async def test_first_ready_return_creates_projection_once(self):
        final_key = {
            **local_key(),
            "display_name": "abcd...mnop",
        }

        with (
            self._mock_api(ready_access()),
            patch(
                "bot.handlers.user.payments.saas._resolve_local_projection_tariffs",
                return_value=[{"id": LOCAL_TARIFF_ID}],
            ),
            patch("database.requests.get_user_internal_id", return_value=USER_ID),
            patch("database.requests.get_all_tariffs", return_value=[{"id": LOCAL_TARIFF_ID}]),
            patch("database.requests.get_key_details_for_user", return_value=final_key),
            patch("database.db_keys.find_materialized_key_for_user", return_value=None),
            patch(
                "database.db_keys.create_materialized_vpn_key_from_saas",
                return_value=55,
            ) as create_key,
            patch("database.payment_return_projection.refresh_materialized_key_from_saas") as refresh_key,
            patch(
                "database.requests.get_active_servers",
                return_value=[{"id": 3}],
            ),
            patch.object(
                payment_return,
                "_local_key_from_declared_projection",
                return_value=None,
            ),
        ):
            result = await materialize_ready_payment_return(
                telegram_id=TELEGRAM_ID,
                access_id=ACCESS_ID,
            )

        self.assertEqual(result.outcome, "created")
        refresh_key.assert_not_called()
        create_key.assert_called_once_with(
            user_id=USER_ID,
            server_id=3,
            tariff_id=LOCAL_TARIFF_ID,
            panel_inbound_id=9,
            panel_email="wm_access_123",
            client_uuid="f5ee70ce-8a27-4f15-b81e-edc8a8bd11c4",
            sub_id="abcdefghijklmnop",
            expires_at=EXPIRY,
            traffic_limit=TRAFFIC_LIMIT,
        )


class PaymentReturnDirectDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def verified(self):
        return VerifiedReadyPaymentReturn(
            access_id=ACCESS_ID,
            subscription_url=ready_material()["subscription_url"],
            access=ready_access(),
            material=ready_material(),
        )

    async def test_authoritative_url_is_rendered_before_local_projection(self):
        events = []
        message = MagicMock()
        verified = self.verified()
        projection = PaymentReturnMaterialization(
            key_id=55,
            key=local_key(),
            outcome="created",
        )

        async def render_remote(*args, **kwargs):
            events.append("remote")

        async def project(*args, **kwargs):
            events.append("projection")
            return projection

        async def confirm(*args, **kwargs):
            events.append("confirmation")

        with (
            patch.object(
                payment_return,
                "load_verified_ready_payment_return",
                AsyncMock(return_value=verified),
            ),
            patch.object(
                payment_return,
                "_render_verified_subscription",
                side_effect=render_remote,
            ),
            patch.object(
                payment_return,
                "materialize_ready_payment_return",
                side_effect=project,
            ) as project_mock,
            patch.object(
                payment_return,
                "_render_projection_confirmation",
                side_effect=confirm,
            ),
        ):
            await process_ready_payment_return(
                message=message,
                telegram_id=TELEGRAM_ID,
                access_id=ACCESS_ID,
            )

        self.assertEqual(events, ["remote", "projection", "confirmation"])
        project_mock.assert_awaited_once_with(
            telegram_id=TELEGRAM_ID,
            access_id=ACCESS_ID,
            verified=verified,
        )

    async def test_expected_local_projection_failure_keeps_delivered_url(self):
        verified = self.verified()
        with (
            patch.object(
                payment_return,
                "load_verified_ready_payment_return",
                AsyncMock(return_value=verified),
            ),
            patch.object(
                payment_return,
                "_render_verified_subscription",
                AsyncMock(),
            ) as render_mock,
            patch.object(
                payment_return,
                "materialize_ready_payment_return",
                AsyncMock(
                    side_effect=InternalApiError(
                        "local projection unavailable",
                        code="LOCAL_PROJECTION_NOT_READY",
                    )
                ),
            ),
            patch.object(
                payment_return,
                "_render_projection_confirmation",
                AsyncMock(),
            ) as confirmation_mock,
        ):
            await process_ready_payment_return(
                message=MagicMock(),
                telegram_id=TELEGRAM_ID,
                access_id=ACCESS_ID,
            )

        render_mock.assert_awaited_once()
        confirmation_mock.assert_not_awaited()

    async def test_retryable_local_projection_failure_keeps_delivered_url(self):
        verified = self.verified()
        with (
            patch.object(
                payment_return,
                "load_verified_ready_payment_return",
                AsyncMock(return_value=verified),
            ),
            patch.object(
                payment_return,
                "_render_verified_subscription",
                AsyncMock(),
            ) as render_mock,
            patch.object(
                payment_return,
                "materialize_ready_payment_return",
                AsyncMock(
                    side_effect=InternalApiError(
                        "temporary local projection error",
                        code="LOCAL_PROJECTION_RETRY",
                        retryable=True,
                    )
                ),
            ),
        ):
            await process_ready_payment_return(
                message=MagicMock(),
                telegram_id=TELEGRAM_ID,
                access_id=ACCESS_ID,
            )

        render_mock.assert_awaited_once()

    async def test_unexpected_local_projection_failure_keeps_delivered_url(self):
        verified = self.verified()
        with (
            patch.object(
                payment_return,
                "load_verified_ready_payment_return",
                AsyncMock(return_value=verified),
            ),
            patch.object(
                payment_return,
                "_render_verified_subscription",
                AsyncMock(),
            ) as render_mock,
            patch.object(
                payment_return,
                "materialize_ready_payment_return",
                AsyncMock(side_effect=RuntimeError("sqlite failure")),
            ),
        ):
            await process_ready_payment_return(
                message=MagicMock(),
                telegram_id=TELEGRAM_ID,
                access_id=ACCESS_ID,
            )

        render_mock.assert_awaited_once()

    async def test_direct_renderer_uses_subscription_mode_without_legacy_markup(self):
        verified = self.verified()
        with patch(
            "bot.utils.key_sender_core.render_key_delivery_page",
            new=AsyncMock(),
        ) as render_page:
            await payment_return._render_verified_subscription(
                MagicMock(),
                verified,
            )

        render_page.assert_awaited_once_with(
            unittest.mock.ANY,
            raw_value=verified.subscription_url,
            is_new=True,
            kind="subscription",
            attach_markup=False,
        )


if __name__ == "__main__":
    unittest.main()
