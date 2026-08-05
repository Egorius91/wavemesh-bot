from __future__ import annotations

from pathlib import Path


HANDLER = Path("bot/handlers/user/payments/payment_return.py")
TEST = Path("tests/test_payment_return_handler.py")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


source = HANDLER.read_text(encoding="utf-8")
source = replace_once(
    source,
    "from dataclasses import dataclass\n",
    "from dataclasses import dataclass, field\n",
    "dataclass import",
)
source = replace_once(
    source,
    '''@dataclass(frozen=True)
class PaymentReturnMaterialization:
    key_id: int
    key: dict[str, Any]
    outcome: str


def extract_payment_return_payload''',
    '''@dataclass(frozen=True)
class PaymentReturnMaterialization:
    key_id: int
    key: dict[str, Any]
    outcome: str


@dataclass(frozen=True)
class VerifiedReadyPaymentReturn:
    access_id: str
    subscription_url: str = field(repr=False)
    access: dict[str, Any] = field(repr=False)
    material: dict[str, Any] = field(repr=False)


def extract_payment_return_payload''',
    "verified dataclass",
)
source = replace_once(
    source,
    '''async def materialize_ready_payment_return(
    *,
    telegram_id: int,
    access_id: str,
) -> PaymentReturnMaterialization:
    """Materialize or refresh one local key projection, serialized per access."""
    lock = _ACCESS_LOCKS.setdefault(access_id, asyncio.Lock())
    async with lock:
        dashboard = await internal_api_client.get_telegram_dashboard(telegram_id)
        access = _single_dashboard_access(dashboard, access_id)
        if access.get("status") != "ready":
            raise InternalApiError(
                "Paid access is not ready yet",
                code="ACCESS_MATERIAL_NOT_READY",
                retryable=True,
            )

        material = await internal_api_client.get_access_material(access_id)
        if material.get("ready") is not True:
            raise InternalApiError(
                "Paid access material is not ready yet",
                code="ACCESS_MATERIAL_NOT_READY",
                retryable=True,
            )

        tariffs = await internal_api_client.list_tariffs()
''',
    '''async def load_verified_ready_payment_return(
    *,
    telegram_id: int,
    access_id: str,
) -> VerifiedReadyPaymentReturn:
    """Load one user-owned ready access and its validated SaaS material."""
    dashboard = await internal_api_client.get_telegram_dashboard(telegram_id)
    access = _single_dashboard_access(dashboard, access_id)
    if access.get("status") != "ready":
        raise InternalApiError(
            "Paid access is not ready yet",
            code="ACCESS_MATERIAL_NOT_READY",
            retryable=True,
        )

    material = await internal_api_client.get_access_material(access_id)
    if material.get("ready") is not True:
        raise InternalApiError(
            "Paid access material is not ready yet",
            code="ACCESS_MATERIAL_NOT_READY",
            retryable=True,
        )

    return VerifiedReadyPaymentReturn(
        access_id=access_id,
        subscription_url=str(material["subscription_url"]),
        access=access,
        material=material,
    )


async def materialize_ready_payment_return(
    *,
    telegram_id: int,
    access_id: str,
    verified: VerifiedReadyPaymentReturn | None = None,
) -> PaymentReturnMaterialization:
    """Materialize or refresh one optional local compatibility projection."""
    lock = _ACCESS_LOCKS.setdefault(access_id, asyncio.Lock())
    async with lock:
        resolved = verified or await load_verified_ready_payment_return(
            telegram_id=telegram_id,
            access_id=access_id,
        )
        if resolved.access_id != access_id:
            raise InternalApiError(
                "Verified payment access does not match the requested access",
                code="INTERNAL_API_INVALID_RESPONSE",
            )
        access = resolved.access
        material = resolved.material

        tariffs = await internal_api_client.list_tariffs()
''',
    "materialization loader",
)

render_start = source.find("async def _render_ready_result(")
render_end = source.find("\n\n@router.message(", render_start)
if render_start < 0 or render_end < 0:
    raise RuntimeError("ready renderer block not found")
new_render_block = '''async def _render_verified_subscription(
    message: Message,
    verified: VerifiedReadyPaymentReturn,
) -> None:
    """Deliver the authoritative SaaS URL before any local projection work."""
    from bot.utils.key_sender_core import render_key_delivery_page

    await render_key_delivery_page(
        message,
        raw_value=verified.subscription_url,
        is_new=True,
        kind="subscription",
        attach_markup=False,
    )


async def _render_projection_confirmation(
    message: Message,
    materialization: PaymentReturnMaterialization,
) -> None:
    if materialization.outcome == "created":
        text = (
            "✅ <b>Доступ добавлен в «Мои ключи»</b>\\n\\n"
            "Subscription-ссылка уже выдана выше."
        )
    elif materialization.outcome == "renewed":
        text = (
            "✅ <b>Подписка продлена</b>\\n\\n"
            "Новый срок и тариф синхронизированы с WaveMesh."
        )
    else:
        text = (
            "✅ <b>Доступ уже готов</b>\\n\\n"
            "Subscription-ссылка выдана выше, а ключ доступен в «Моих ключах»."
        )

    await safe_edit_or_send(
        message,
        text,
        reply_markup=_key_button(materialization.key_id),
        force_new=True,
    )


async def process_ready_payment_return(
    *,
    message: Message,
    telegram_id: int,
    access_id: str,
) -> None:
    """Deliver verified SaaS material, then best-effort the legacy projection."""
    verified = await load_verified_ready_payment_return(
        telegram_id=telegram_id,
        access_id=access_id,
    )
    await _render_verified_subscription(message, verified)

    try:
        materialization = await materialize_ready_payment_return(
            telegram_id=telegram_id,
            access_id=access_id,
            verified=verified,
        )
    except InternalApiError as error:
        logger.warning(
            "Payment return local projection skipped: telegram_id=%s "
            "access_id=%s code=%s status=%s retryable=%s",
            telegram_id,
            access_id,
            error.code,
            error.status,
            error.retryable,
        )
        return
    except Exception:
        logger.exception(
            "Unexpected payment return local projection error: telegram_id=%s "
            "access_id=%s",
            telegram_id,
            access_id,
        )
        return

    await _render_projection_confirmation(message, materialization)
'''
source = source[:render_start] + new_render_block + source[render_end:]

old_handler = '''    try:
        materialization = await materialize_ready_payment_return(
            telegram_id=telegram_user.id,
            access_id=result["access_id"],
        )
    except InternalApiError as error:
        logger.warning(
            "Payment return materialization failed: telegram_id=%s access_id=%s "
            "code=%s status=%s retryable=%s",
            telegram_user.id,
            result.get("access_id"),
            error.code,
            error.status,
            error.retryable,
        )
        text = (
            payment_return_status_text("access_creating")
            if error.retryable
            else payment_return_status_text("support_error")
        )
        await safe_edit_or_send(message, text, force_new=True)
        return
    except Exception:
        logger.exception(
            "Unexpected payment return materialization error: telegram_id=%s "
            "access_id=%s",
            telegram_user.id,
            result.get("access_id"),
        )
        await safe_edit_or_send(
            message,
            payment_return_status_text("support_error"),
            force_new=True,
        )
        return

    await _render_ready_result(message, materialization)'''
new_handler = '''    try:
        await process_ready_payment_return(
            message=message,
            telegram_id=telegram_user.id,
            access_id=result["access_id"],
        )
    except InternalApiError as error:
        logger.warning(
            "Payment return ready material unavailable: telegram_id=%s "
            "access_id=%s code=%s status=%s retryable=%s",
            telegram_user.id,
            result.get("access_id"),
            error.code,
            error.status,
            error.retryable,
        )
        text = (
            payment_return_status_text("access_creating")
            if error.retryable
            else payment_return_status_text("support_error")
        )
        await safe_edit_or_send(message, text, force_new=True)
    except Exception:
        logger.exception(
            "Unexpected payment return ready-material error: telegram_id=%s "
            "access_id=%s",
            telegram_user.id,
            result.get("access_id"),
        )
        await safe_edit_or_send(
            message,
            payment_return_status_text("support_error"),
            force_new=True,
        )'''
source = replace_once(source, old_handler, new_handler, "ready handler")
HANDLER.write_text(source, encoding="utf-8")

test_source = TEST.read_text(encoding="utf-8")
test_source = replace_once(
    test_source,
    '''    materialize_ready_payment_return,
    payment_return_status_text,
)''',
    '''    VerifiedReadyPaymentReturn,
    materialize_ready_payment_return,
    payment_return_status_text,
    process_ready_payment_return,
)''',
    "test imports",
)
append = '''

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
'''
if "class PaymentReturnDirectDeliveryTests" not in test_source:
    marker = '\n\nif __name__ == "__main__":\n'
    if marker not in test_source:
        raise RuntimeError("test main marker not found")
    test_source = test_source.replace(marker, append + marker, 1)
TEST.write_text(test_source, encoding="utf-8")
