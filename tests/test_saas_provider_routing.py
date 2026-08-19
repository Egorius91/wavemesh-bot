from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from bot.handlers.user.payments import provider_routing as routing


class SaasProviderRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_provider_callback_parsers_use_compact_aliases(self) -> None:
        self.assertEqual(
            routing._parse_new_provider_callback("saas_np:yk:tariff-123"),
            ("YOOKASSA", "tariff-123"),
        )
        self.assertEqual(
            routing._parse_new_provider_callback("saas_np:pg:tariff-123"),
            ("PLATEGA", "tariff-123"),
        )
        self.assertEqual(
            routing._parse_renew_provider_callback("saas_rp:42:pg:tariff-123"),
            (42, "PLATEGA", "tariff-123"),
        )
        self.assertIsNone(
            routing._parse_new_provider_callback("saas_np:xx:tariff-123")
        )
        self.assertIsNone(
            routing._parse_renew_provider_callback("saas_rp:x:pg:tariff-123")
        )

    def test_provider_callbacks_fit_telegram_limit_for_cuid_tariff(self) -> None:
        tariff_id = "cm1234567890abcdefghijklmn"
        new_callback = f"{routing._NEW_PROVIDER_PREFIX}:pg:{tariff_id}"
        renew_callback = f"{routing._RENEW_PROVIDER_PREFIX}:123456789:yk:{tariff_id}"
        self.assertLessEqual(len(new_callback.encode("utf-8")), 64)
        self.assertLessEqual(len(renew_callback.encode("utf-8")), 64)

    async def test_single_provider_preserves_default_routing_for_new_access(self) -> None:
        callback = SimpleNamespace(
            data="saas_new_checkout:tariff-1",
            id="callback-1",
            from_user=SimpleNamespace(id=1001),
            message=object(),
            answer=AsyncMock(),
        )
        tariff = {
            "tariff_id": "tariff-1",
            "name": "30 дней",
            "billing_mode": "ONE_TIME",
        }
        create = AsyncMock()
        with (
            patch.object(
                routing,
                "_load_new_context",
                AsyncMock(return_value=("user-1", tariff, "ONE_TIME")),
            ),
            patch.object(
                routing,
                "_load_provider_names",
                AsyncMock(return_value=["PLATEGA"]),
            ),
            patch.object(routing, "_create_new_order", create),
        ):
            await routing.route_new_checkout(callback)

        create.assert_awaited_once_with(
            callback,
            user_id="user-1",
            tariff=tariff,
            billing_mode="ONE_TIME",
            provider=None,
        )

    async def test_multiple_providers_require_selection_before_new_checkout(self) -> None:
        callback = SimpleNamespace(
            data="saas_new_checkout:tariff-1",
            id="callback-2",
            from_user=SimpleNamespace(id=1002),
            message=object(),
            answer=AsyncMock(),
        )
        tariff = {
            "tariff_id": "tariff-1",
            "name": "30 дней",
            "billing_mode": "ONE_TIME",
        }
        create = AsyncMock()
        edit = AsyncMock()
        with (
            patch.object(
                routing,
                "_load_new_context",
                AsyncMock(return_value=("user-2", tariff, "ONE_TIME")),
            ),
            patch.object(
                routing,
                "_load_provider_names",
                AsyncMock(return_value=["YOOKASSA", "PLATEGA"]),
            ),
            patch.object(routing, "_create_new_order", create),
            patch.object(routing, "safe_edit_or_send", edit),
        ):
            await routing.route_new_checkout(callback)

        create.assert_not_awaited()
        edit.assert_awaited_once()
        callback.answer.assert_awaited_once_with()

    async def test_explicit_new_provider_is_revalidated_and_forwarded(self) -> None:
        callback = SimpleNamespace(
            data="saas_np:pg:tariff-1",
            id="callback-3",
            from_user=SimpleNamespace(id=1003),
            message=object(),
            answer=AsyncMock(),
        )
        tariff = {
            "tariff_id": "tariff-1",
            "name": "30 дней",
            "billing_mode": "ONE_TIME",
        }
        create = AsyncMock()
        with (
            patch.object(
                routing,
                "_load_new_context",
                AsyncMock(return_value=("user-3", tariff, "ONE_TIME")),
            ),
            patch.object(
                routing,
                "_load_provider_names",
                AsyncMock(return_value=["YOOKASSA", "PLATEGA"]),
            ),
            patch.object(routing, "_create_new_order", create),
        ):
            await routing.create_new_checkout_with_provider(callback)

        create.assert_awaited_once_with(
            callback,
            user_id="user-3",
            tariff=tariff,
            billing_mode="ONE_TIME",
            provider="PLATEGA",
        )

    async def test_stale_explicit_new_provider_fails_before_checkout(self) -> None:
        callback = SimpleNamespace(
            data="saas_np:pg:tariff-1",
            id="callback-4",
            from_user=SimpleNamespace(id=1004),
            message=object(),
            answer=AsyncMock(),
        )
        tariff = {
            "tariff_id": "tariff-1",
            "name": "30 дней",
            "billing_mode": "ONE_TIME",
        }
        create = AsyncMock()
        with (
            patch.object(
                routing,
                "_load_new_context",
                AsyncMock(return_value=("user-4", tariff, "ONE_TIME")),
            ),
            patch.object(
                routing,
                "_load_provider_names",
                AsyncMock(return_value=["YOOKASSA"]),
            ),
            patch.object(routing, "_create_new_order", create),
        ):
            await routing.create_new_checkout_with_provider(callback)

        create.assert_not_awaited()
        callback.answer.assert_awaited_once_with(
            "Выбранный способ оплаты больше недоступен.",
            show_alert=True,
        )

    async def test_single_provider_preserves_default_routing_for_renewal(self) -> None:
        callback = SimpleNamespace(
            data="saas_checkout:42:tariff-1",
            id="callback-5",
            from_user=SimpleNamespace(id=1005),
            message=object(),
            answer=AsyncMock(),
        )
        key = {"display_name": "Key"}
        tariff = {
            "tariff_id": "tariff-1",
            "name": "30 дней",
            "billing_mode": "ONE_TIME",
        }
        create = AsyncMock()
        with (
            patch.object(
                routing,
                "_load_renew_context",
                AsyncMock(
                    return_value=(key, tariff, "ONE_TIME", "access-12345678")
                ),
            ),
            patch.object(
                routing,
                "_load_provider_names",
                AsyncMock(return_value=["YOOKASSA"]),
            ),
            patch.object(routing, "_create_renew_order", create),
        ):
            await routing.route_renew_checkout(callback)

        create.assert_awaited_once_with(
            callback,
            key_id=42,
            key=key,
            tariff=tariff,
            billing_mode="ONE_TIME",
            access_id="access-12345678",
            provider=None,
        )

    async def test_explicit_renew_provider_is_revalidated_and_forwarded(self) -> None:
        callback = SimpleNamespace(
            data="saas_rp:42:yk:tariff-1",
            id="callback-6",
            from_user=SimpleNamespace(id=1006),
            message=object(),
            answer=AsyncMock(),
        )
        key = {"display_name": "Key"}
        tariff = {
            "tariff_id": "tariff-1",
            "name": "30 дней",
            "billing_mode": "ONE_TIME",
        }
        create = AsyncMock()
        with (
            patch.object(
                routing,
                "_load_renew_context",
                AsyncMock(
                    return_value=(key, tariff, "ONE_TIME", "access-12345678")
                ),
            ),
            patch.object(
                routing,
                "_load_provider_names",
                AsyncMock(return_value=["YOOKASSA", "PLATEGA"]),
            ),
            patch.object(routing, "_create_renew_order", create),
        ):
            await routing.create_renew_checkout_with_provider(callback)

        create.assert_awaited_once_with(
            callback,
            key_id=42,
            key=key,
            tariff=tariff,
            billing_mode="ONE_TIME",
            access_id="access-12345678",
            provider="YOOKASSA",
        )


if __name__ == "__main__":
    unittest.main()
