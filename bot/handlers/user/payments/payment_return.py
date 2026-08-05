"""Opaque Telegram payment-return deep-link flow for WaveMesh SaaS."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.internal_api import (
    InternalApiError,
    internal_api_client,
    schedule_telegram_user_upsert,
)
from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

_PAYMENT_RETURN_PAYLOAD_PATTERN = re.compile(r"^pay_[A-Za-z0-9_-]{32}$")
_PAYMENT_RETURN_COMMAND_PATTERN = re.compile(
    r"^/start(?:@[A-Za-z][A-Za-z0-9_]{4,31})?\s+"
    r"(pay_[A-Za-z0-9_-]{32})\s*$"
)

_ACCESS_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
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


def extract_payment_return_payload(text: str | None) -> str | None:
    """Extract only the exact opaque payload accepted by the SaaS contract."""
    if not isinstance(text, str):
        return None
    match = _PAYMENT_RETURN_COMMAND_PATTERN.fullmatch(text)
    return match.group(1) if match else None


def payment_return_status_text(status: str) -> str:
    """Return stable user-facing copy without reflecting the opaque token."""
    messages = {
        "pending": (
            "⏳ <b>Платёж ещё обрабатывается</b>\n\n"
            "YooKassa пока не подтвердила оплату. Не создавайте новый платёж — "
            "откройте эту же ссылку немного позже."
        ),
        "cancelled": (
            "↩️ <b>Оплата не завершена</b>\n\n"
            "Заказ отменён или платёж не был завершён. Можно вернуться к тарифам "
            "и создать новую оплату."
        ),
        "access_creating": (
            "✅ <b>Оплата подтверждена</b>\n\n"
            "Entry Node создаёт доступ. Не создавайте новый платёж — откройте эту "
            "же ссылку через несколько секунд."
        ),
        "support_error": (
            "⚠️ <b>Оплата требует проверки</b>\n\n"
            "Не создавайте новый платёж. Заказ сохранён в WaveMesh; обратитесь в "
            "поддержку, чтобы мы проверили создание доступа."
        ),
    }
    try:
        return messages[status]
    except KeyError as error:
        raise InternalApiError(
            "Unsupported payment return status",
            code="INTERNAL_API_INVALID_RESPONSE",
        ) from error


def _normalize_expiry(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _local_projection_needs_refresh(
    existing: dict[str, Any],
    *,
    tariff_id: int,
    expires_at: str,
    traffic_limit: int,
) -> bool:
    """Compare all commercial fields refreshed by a verified paid period."""
    try:
        current_expiry = _normalize_expiry(existing.get("expires_at"))
        current_tariff_id = int(existing.get("tariff_id") or 0)
        current_traffic_limit = max(0, int(existing.get("traffic_limit") or 0))
    except (TypeError, ValueError):
        return True

    return (
        current_expiry != expires_at
        or current_tariff_id != tariff_id
        or current_traffic_limit != traffic_limit
    )


def _single_dashboard_access(
    dashboard: dict[str, Any],
    access_id: str,
) -> dict[str, Any]:
    raw_accesses = dashboard.get("accesses")
    accesses = raw_accesses if isinstance(raw_accesses, list) else []
    matches = [
        item
        for item in accesses
        if isinstance(item, dict) and item.get("access_id") == access_id
    ]
    if len(matches) != 1:
        raise InternalApiError(
            "SaaS returned an ambiguous payment access",
            code="INTERNAL_API_INVALID_RESPONSE",
        )
    return matches[0]


def _single_saas_tariff(
    tariffs: list[dict[str, Any]],
    tariff_id: Any,
) -> dict[str, Any]:
    matches = [
        item
        for item in tariffs
        if isinstance(item, dict) and item.get("tariff_id") == tariff_id
    ]
    if len(matches) != 1:
        raise InternalApiError(
            "Paid SaaS tariff is missing or ambiguous",
            code="INTERNAL_API_INVALID_RESPONSE",
        )
    return matches[0]


def _local_key_from_declared_projection(
    access: dict[str, Any],
    telegram_id: int,
    material: dict[str, Any],
) -> dict[str, Any] | None:
    raw_key_id = access.get("legacy_key_id")
    if raw_key_id in {None, ""}:
        return None

    try:
        key_id = int(raw_key_id)
    except (TypeError, ValueError) as error:
        raise InternalApiError(
            "SaaS legacy key projection is invalid",
            code="INTERNAL_API_INVALID_RESPONSE",
        ) from error

    from database.requests import get_key_details_for_user

    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        raise InternalApiError(
            "SaaS legacy key projection is missing locally",
            code="INTERNAL_API_INVALID_RESPONSE",
        )

    if (
        key.get("client_uuid") != material.get("client_uuid")
        or key.get("panel_email") != material.get("panel_email")
        or key.get("sub_id") != material.get("sub_id")
    ):
        raise InternalApiError(
            "SaaS legacy key projection does not match access material",
            code="INTERNAL_API_INVALID_RESPONSE",
        )

    return key


async def load_verified_ready_payment_return(
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
        saas_tariff = _single_saas_tariff(tariffs, access.get("tariff_id"))

        from bot.handlers.user.payments.saas import (
            _resolve_local_projection_tariffs,
        )
        from database.db_keys import (
            create_materialized_vpn_key_from_saas,
            find_materialized_key_for_user,
        )
        from database.payment_return_projection import (
            refresh_materialized_key_from_saas,
        )
        from database.requests import (
            get_active_servers,
            get_all_tariffs,
            get_key_details_for_user,
            get_user_internal_id,
        )

        user_id = get_user_internal_id(telegram_id)
        if not user_id:
            raise InternalApiError(
                "Local Telegram user projection is missing",
                code="LOCAL_PROJECTION_NOT_READY",
            )

        local_tariffs = _resolve_local_projection_tariffs(
            get_all_tariffs(include_hidden=True),
            saas_tariff,
        )
        if len(local_tariffs) != 1:
            raise InternalApiError(
                "Local SaaS tariff projection is ambiguous",
                code="LOCAL_PROJECTION_NOT_READY",
            )

        local_tariff_id = int(local_tariffs[0]["id"])
        expires_at = _normalize_expiry(access.get("expires_at"))
        try:
            traffic_limit = max(0, int(access.get("traffic_limit_bytes") or 0))
        except (TypeError, ValueError) as error:
            raise InternalApiError(
                "SaaS traffic limit is invalid",
                code="INTERNAL_API_INVALID_RESPONSE",
            ) from error

        existing = _local_key_from_declared_projection(
            access,
            telegram_id,
            material,
        )
        if existing is None:
            existing = find_materialized_key_for_user(
                int(user_id),
                str(material["client_uuid"]),
                str(material["panel_email"]),
                str(material["sub_id"]),
            )

        if existing:
            key_id = int(existing["id"])
            if _local_projection_needs_refresh(
                existing,
                tariff_id=local_tariff_id,
                expires_at=expires_at,
                traffic_limit=traffic_limit,
            ):
                if not refresh_materialized_key_from_saas(
                    key_id=key_id,
                    tariff_id=local_tariff_id,
                    expires_at=expires_at,
                    traffic_limit=traffic_limit,
                ):
                    raise InternalApiError(
                        "Local key renewal projection failed",
                        code="LOCAL_PROJECTION_FAILED",
                    )
                outcome = "renewed"
            else:
                outcome = "existing"
        else:
            servers = get_active_servers()
            if len(servers) != 1:
                raise InternalApiError(
                    "Local SaaS server projection is ambiguous",
                    code="LOCAL_PROJECTION_NOT_READY",
                )
            key_id = create_materialized_vpn_key_from_saas(
                user_id=int(user_id),
                server_id=int(servers[0]["id"]),
                tariff_id=local_tariff_id,
                panel_inbound_id=int(material["primary_inbound_id"]),
                panel_email=str(material["panel_email"]),
                client_uuid=str(material["client_uuid"]),
                sub_id=str(material["sub_id"]),
                expires_at=expires_at,
                traffic_limit=traffic_limit,
            )
            outcome = "created"

        await internal_api_client.link_access_projection(
            access_id=access_id,
            telegram_id=telegram_id,
            legacy_key_id=key_id,
            idempotency_key=f"paid-access-projection-{access_id}-{key_id}",
        )

        key = get_key_details_for_user(key_id, telegram_id)
        if not key:
            raise InternalApiError(
                "Materialized local key is missing",
                code="LOCAL_PROJECTION_FAILED",
            )

        return PaymentReturnMaterialization(
            key_id=key_id,
            key=key,
            outcome=outcome,
        )


def _key_button(key_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔑 Открыть ключ",
            callback_data=f"key:{key_id}",
        )
    )
    return builder.as_markup()


async def _render_verified_subscription(
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
            "✅ <b>Доступ добавлен в «Мои ключи»</b>\n\n"
            "Subscription-ссылка уже выдана выше."
        )
    elif materialization.outcome == "renewed":
        text = (
            "✅ <b>Подписка продлена</b>\n\n"
            "Новый срок и тариф синхронизированы с WaveMesh."
        )
    else:
        text = (
            "✅ <b>Доступ уже готов</b>\n\n"
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


@router.message(
    Command("start"),
    StateFilter("*"),
    F.text.regexp(_PAYMENT_RETURN_COMMAND_PATTERN.pattern),
)
async def payment_return_deeplink(
    message: Message,
    state: FSMContext,
    command: CommandObject,
) -> None:
    """Resolve one opaque payment-return token and project only verified state."""
    telegram_user = message.from_user
    if telegram_user is None:
        return

    payload = command.args or extract_payment_return_payload(message.text)
    if not isinstance(payload, str) or not _PAYMENT_RETURN_PAYLOAD_PATTERN.fullmatch(payload):
        return

    from database.requests import get_or_create_user

    local_user, _ = get_or_create_user(
        telegram_user.id,
        telegram_user.username,
        first_name=getattr(telegram_user, "first_name", None),
        last_name=getattr(telegram_user, "last_name", None),
    )

    schedule_telegram_user_upsert(
        telegram_id=telegram_user.id,
        username=telegram_user.username,
        first_name=getattr(telegram_user, "first_name", None),
        last_name=getattr(telegram_user, "last_name", None),
        is_bot_blocked=False,
    )

    await state.clear()

    if local_user.get("is_banned"):
        await safe_edit_or_send(
            message,
            "⛔ <b>Доступ заблокирован</b>\n\nОбратитесь в поддержку.",
            force_new=True,
        )
        return

    try:
        result = await internal_api_client.resolve_payment_return(payload)
    except InternalApiError as error:
        logger.warning(
            "Payment return resolution failed: telegram_id=%s code=%s "
            "status=%s retryable=%s",
            telegram_user.id,
            error.code,
            error.status,
            error.retryable,
        )
        if error.code == "PAYMENT_RETURN_TOKEN_EXPIRED" or error.status == 410:
            text = (
                "⌛ <b>Ссылка возврата устарела</b>\n\n"
                "Откройте «Мои ключи»: подтверждённый доступ мог быть создан без "
                "этой ссылки. При необходимости обратитесь в поддержку."
            )
        elif error.code in {
            "PAYMENT_RETURN_TOKEN_NOT_FOUND",
            "PAYMENT_RETURN_TOKEN_INVALID",
        } or error.status == 404:
            text = (
                "❌ <b>Ссылка возврата не найдена</b>\n\n"
                "Проверьте, что открыли ссылку именно после оплаты WaveMesh."
            )
        elif error.retryable:
            text = (
                "⏳ <b>Проверка временно недоступна</b>\n\n"
                "Не создавайте новый платёж. Повторно откройте эту же ссылку позже."
            )
        else:
            text = payment_return_status_text("support_error")
        await safe_edit_or_send(message, text, force_new=True)
        return

    status = result["status"]
    if status != "ready":
        await safe_edit_or_send(
            message,
            payment_return_status_text(status),
            force_new=True,
        )
        return

    try:
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
        )
