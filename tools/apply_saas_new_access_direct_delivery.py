from __future__ import annotations

from pathlib import Path


SAAS = Path("bot/handlers/user/payments/saas.py")
TEST = Path("tests/test_saas_new_access_delivery.py")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


source = SAAS.read_text(encoding="utf-8")
source = replace_once(
    source,
    '''from bot.services.internal_api import (
    InternalApiError,
    internal_api_client,
)
''',
    '''from bot.services.internal_api import (
    InternalApiError,
    internal_api_client,
)
from bot.handlers.user.payments.payment_return import process_ready_payment_return
''',
    "direct delivery import",
)
start = source.index(
    '@router.callback_query(F.data.startswith(f"{_NEW_CHECK_PREFIX}:"))'
)
end = source.index("\n\nasync def _load_checkout_context(", start)
replacement = '''@router.callback_query(F.data.startswith(f"{_NEW_CHECK_PREFIX}:"))
async def saas_new_access_check(callback: CallbackQuery) -> None:
    """Resolve one paid order and use the shared verified delivery workflow."""
    order_id = _parse_single_value_callback(callback.data, _NEW_CHECK_PREFIX)
    if order_id is None:
        await callback.answer("Некорректный заказ.", show_alert=True)
        return

    try:
        dashboard = await internal_api_client.get_telegram_dashboard(
            callback.from_user.id,
        )
        accesses = dashboard.get("accesses")
        matches = [
            item
            for item in accesses
            if isinstance(item, dict)
            and item.get("source_order_id") == order_id
        ] if isinstance(accesses, list) else []

        if not matches:
            await callback.answer(
                "Платёж ещё не подтверждён YooKassa. Попробуйте немного позже.",
                show_alert=True,
            )
            return
        if len(matches) != 1:
            raise InternalApiError("SaaS returned ambiguous paid access")

        access = matches[0]
        if access.get("status") != "ready":
            await callback.answer(
                "Оплата принята. Entry Node ещё создаёт ключ — "
                "проверьте снова через несколько секунд.",
                show_alert=True,
            )
            return

        access_id = access.get("access_id")
        if not isinstance(access_id, str) or not access_id:
            raise InternalApiError("Paid SaaS access has no access_id")

        await callback.answer("Проверяем готовый доступ…")
        await process_ready_payment_return(
            message=callback.message,
            telegram_id=callback.from_user.id,
            access_id=access_id,
        )
    except InternalApiError as error:
        logger.warning(
            "SaaS paid access delivery failed: telegram_id=%s order_id=%s "
            "code=%s status=%s retryable=%s",
            callback.from_user.id,
            order_id,
            error.code,
            error.status,
            error.retryable,
        )
        await safe_edit_or_send(
            callback.message,
            (
                "⏳ <b>Оплата получена</b>\\n\\n"
                "Готовый доступ пока не удалось получить. "
                "Не создавайте новый платёж; повторите проверку позже."
            ),
            force_new=True,
        )
    except Exception as error:  # noqa: BLE001 - Telegram handler boundary
        logger.exception(
            "Unexpected SaaS paid access delivery error: telegram_id=%s "
            "order_id=%s code=%s",
            callback.from_user.id,
            order_id,
            type(error).__name__,
        )
        await safe_edit_or_send(
            callback.message,
            (
                "⏳ <b>Оплата получена</b>\\n\\n"
                "Доступ сохранён в WaveMesh, но его пока не удалось показать. "
                "Повторите проверку позже."
            ),
            force_new=True,
        )
'''
source = source[:start] + replacement + source[end:]
SAAS.write_text(source, encoding="utf-8")

TEST.write_text(
    '''from __future__ import annotations

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
        source = saas.__file__
        self.assertIsNotNone(source)
        text = open(source, encoding="utf-8").read()
        start = text.index("async def saas_new_access_check")
        end = text.index("async def _load_checkout_context", start)
        function_text = text[start:end]

        self.assertNotIn("create_materialized_vpn_key_from_saas", function_text)
        self.assertNotIn("get_active_servers", function_text)
        self.assertNotIn("list_tariffs", function_text)
        self.assertIn("process_ready_payment_return", function_text)


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)
