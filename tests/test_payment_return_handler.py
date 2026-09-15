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
LOCAL_TARIFF_ID = 1
REMOTE_TARIFF_ID = "tariff-12345678"
EXPIRY = "2026-09-01 12:30:00"
TRAFFIC_LIMIT = 1024


def ready_access(*, legacy_key_id=None, expires_at=EXPIRY):
    return {
        "access_id": ACCESS_ID,
        "status": "ready", "authority": "managed", "enabled": True, "desired_version": 1,
        "subscription_url": "https://entry.example.invalid/sub/value",
        "tariff_id": REMOTE_TARIFF_ID,
        "expires_at": expires_at.replace(" ", "T")+"Z",
        "traffic_limit_bytes": str(TRAFFIC_LIMIT),
        "legacy_key_id": legacy_key_id,
    }


def ready_material():
    return {
        "access_id": ACCESS_ID,
        "status": "ready",
        "ready": True,
        "node_id": "node-1",
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
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from database import connection
        from database.migrations import migration_initial, MIGRATIONS
        payment_return._ACCESS_LOCKS.clear()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(connection, "DB_PATH", Path(self.tmp.name)/"payment.sqlite").start()
        with connection.get_db() as conn:
            migration_initial(conn)
            for migration in MIGRATIONS.values():
                migration(conn)
            conn.execute("INSERT INTO users(id,telegram_id) VALUES (?,?)", (USER_ID,TELEGRAM_ID))
        patch("bot.handlers.user.payments.saas._resolve_local_projection_tariffs", return_value=[{"id":LOCAL_TARIFF_ID}]).start()

    @contextmanager
    def _mock_api(self, access):
        dashboard = {"user":{"user_id":"saas-user", "tenant_id":"tenant"}, "accesses":[access]}
        with (
            patch.object(payment_return.internal_api_client, "tenant_id", "tenant"),
            patch.object(payment_return.internal_api_client, "get_telegram_dashboard", AsyncMock(return_value=dashboard)),
            patch.object(payment_return.internal_api_client, "get_access_material", AsyncMock(return_value=ready_material())) as material,
            patch.object(payment_return.internal_api_client, "list_tariffs", AsyncMock(return_value=[{"tariff_id":REMOTE_TARIFF_ID}])),
            patch.object(payment_return.internal_api_client, "link_access_projection", AsyncMock()) as link,
            patch("database.requests.get_active_servers", side_effect=AssertionError("No local panel discovery")),
        ):
            yield link, material

    async def project(self):
        return await materialize_ready_payment_return(telegram_id=TELEGRAM_ID, access_id=ACCESS_ID)

    async def test_repeated_ready_return_reuses_existing_projection(self):
        with self._mock_api(ready_access()) as (link, _):
            first, second = await self.project(), await self.project()
        self.assertEqual(first.key_id, second.key_id)
        self.assertEqual((first.outcome,second.outcome),("created","existing"))
        self.assertIsNone(first.key["server_id"])
        self.assertEqual(link.await_args_list[0],link.await_args_list[1])

    async def test_ready_renewal_refreshes_existing_projection_once(self):
        access = ready_access()
        with self._mock_api(access) as (_, material):
            first = await self.project()
            access.update(desired_version=2,expires_at="2026-10-01T12:30:00Z",legacy_key_id=str(first.key_id))
            material.return_value = ready_material() | {"desired_version":2}
            second, third = await self.project(), await self.project()
        self.assertEqual((first.key_id,second.key_id,third.key_id),(first.key_id,)*3)
        self.assertEqual(second.key["expires_at"],"2026-10-01 12:30:00")
        self.assertEqual((second.outcome,third.outcome),("renewed","existing"))

    async def test_lost_projection_link_response_never_creates_second_key(self):
        with self._mock_api(ready_access()) as (link, _):
            link.side_effect = [TimeoutError(), {}]
            with self.assertRaises(TimeoutError):
                await self.project()
            result = await self.project()
        self.assertEqual(result.outcome,"existing")
        self.assertEqual(link.await_args_list[0],link.await_args_list[1])

    async def test_changed_version_or_nonmanaged_access_never_projects(self):
        for changes in ({"desired_version":2},{"authority":"legacy_snapshot"},{"enabled":False}):
            with self._mock_api(ready_access() | changes), self.assertRaises(InternalApiError):
                await self.project()

    async def test_replacement_updates_same_serverless_projection(self):
        from bot.handlers.user.payments.saas import _apply_replacement_material
        from database.requests import get_key_details_for_user
        from database.saas_access_projection import get_binding
        access = ready_access()
        with self._mock_api(access) as (_, material):
            first = await self.project()
            access["desired_version"] = 2
            replacement = ready_material() | {"desired_version":2,"client_uuid":"rotated","sub_id":"rotated-sub"}
            material.return_value = replacement
            await _apply_replacement_material(first.key,replacement,TELEGRAM_ID)
        updated = get_key_details_for_user(first.key_id,TELEGRAM_ID)
        self.assertEqual(updated["client_uuid"],"rotated")
        self.assertIsNone(updated["server_id"])
        self.assertEqual(get_binding(first.key_id)["node_id"],"node-1")


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
