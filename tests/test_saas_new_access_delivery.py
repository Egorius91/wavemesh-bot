from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.user.payments import saas
from bot.services.internal_api import InternalApiError


class SaasNewAccessDirectDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def callback(self, *, order_id: str = "order-1"):
        callback = MagicMock()
        callback.data = f"saas_new_check:{order_id}"
        callback.from_user = SimpleNamespace(id=123456)
        callback.message = MagicMock()
        callback.answer = AsyncMock()
        return callback

    async def test_ready_access_uses_shared_direct_delivery_once(self) -> None:
        callback = self.callback()
        dashboard = {
            "accesses": [
                {
                    "source_order_id": "order-1",
                    "access_id": "access-1",
                    "status": "ready",
                }
            ]
        }

        with (
            patch.object(
                saas.internal_api_client,
                "get_telegram_dashboard",
                AsyncMock(return_value=dashboard),
            ),
            patch.object(
                saas,
                "process_ready_payment_return",
                AsyncMock(),
            ) as deliver,
        ):
            await saas.saas_new_access_check(callback)

        callback.answer.assert_awaited_once_with("Проверяем готовый доступ…")
        deliver.assert_awaited_once_with(
            message=callback.message,
            telegram_id=123456,
            access_id="access-1",
        )

    async def test_unconfirmed_order_does_not_invoke_delivery(self) -> None:
        callback = self.callback()
        with (
            patch.object(
                saas.internal_api_client,
                "get_telegram_dashboard",
                AsyncMock(return_value={"accesses": []}),
            ),
            patch.object(
                saas,
                "process_ready_payment_return",
                AsyncMock(),
            ) as deliver,
        ):
            await saas.saas_new_access_check(callback)

        deliver.assert_not_awaited()
        callback.answer.assert_awaited_once()

    async def test_materializing_access_does_not_invoke_delivery(self) -> None:
        callback = self.callback()
        dashboard = {
            "accesses": [
                {
                    "source_order_id": "order-1",
                    "access_id": "access-1",
                    "status": "materializing",
                }
            ]
        }
        with (
            patch.object(
                saas.internal_api_client,
                "get_telegram_dashboard",
                AsyncMock(return_value=dashboard),
            ),
            patch.object(
                saas,
                "process_ready_payment_return",
                AsyncMock(),
            ) as deliver,
        ):
            await saas.saas_new_access_check(callback)

        deliver.assert_not_awaited()
        callback.answer.assert_awaited_once()

    async def test_remote_delivery_failure_uses_safe_retry_message(self) -> None:
        callback = self.callback()
        dashboard = {
            "accesses": [
                {
                    "source_order_id": "order-1",
                    "access_id": "access-1",
                    "status": "ready",
                }
            ]
        }
        with (
            patch.object(
                saas.internal_api_client,
                "get_telegram_dashboard",
                AsyncMock(return_value=dashboard),
            ),
            patch.object(
                saas,
                "process_ready_payment_return",
                AsyncMock(
                    side_effect=InternalApiError(
                        "material not ready",
                        code="ACCESS_MATERIAL_NOT_READY",
                        retryable=True,
                    )
                ),
            ),
            patch.object(
                saas,
                "safe_edit_or_send",
                AsyncMock(),
            ) as render,
        ):
            await saas.saas_new_access_check(callback)

        callback.answer.assert_awaited_once_with("Проверяем готовый доступ…")
        render.assert_awaited_once()
        rendered_text = render.await_args.args[1]
        self.assertIn("Не создавайте новый платёж", rendered_text)

    def test_duplicate_projection_code_is_removed(self) -> None:
        function_text = inspect.getsource(
            saas.saas_new_access_check,
        )

        self.assertNotIn("create_materialized_vpn_key_from_saas", function_text)
        self.assertNotIn("get_active_servers", function_text)
        self.assertNotIn("list_tariffs", function_text)
        self.assertIn("process_ready_payment_return", function_text)


if __name__ == "__main__":
    unittest.main()
