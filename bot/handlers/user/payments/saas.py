"""SaaS checkout flow for Telegram renewals.

This router is included only in WaveMesh SaaS client mode and is registered
before legacy payment routers. It performs read-only ownership checks against
the local key projection, then creates the commercial order exclusively in the
WaveMesh SaaS Internal API for the exact mapped access.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.internal_api import (
    InternalApiError,
    internal_api_client,
)
from bot.handlers.user.payments.payment_return import process_ready_payment_return
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

_CALLBACK_PREFIX = "saas_checkout"
_NEW_CHECKOUT_PREFIX = "saas_new_checkout"
_NEW_CHECK_PREFIX = "saas_new_check"


def _matching_accesses(accesses: Any, key_id: int) -> list[dict[str, Any]]:
    """Return SaaS accesses explicitly mapped to the selected legacy key."""
    if not isinstance(accesses, list):
        return []
    legacy_key_id = str(key_id)
    return [
        access
        for access in accesses
        if isinstance(access, dict)
        and str(access.get("legacy_key_id") or "") == legacy_key_id
    ]


def _tariff_button_text(tariff: dict[str, Any]) -> str:
    name = str(tariff.get("name") or "Тариф")
    days = tariff.get("duration_days")
    price = tariff.get("price_rub")

    parts = [name]
    if isinstance(days, int) and days > 0:
        parts.append(f"{days} дн.")
    if isinstance(price, (int, float)) and price > 0:
        parts.append(f"{price:g} ₽")
    return " · ".join(parts)


def _parse_checkout_callback(data: str) -> tuple[int, str] | None:
    try:
        prefix, raw_key_id, tariff_id = data.split(":", 2)
        if prefix != _CALLBACK_PREFIX or not tariff_id:
            return None
        return int(raw_key_id), tariff_id
    except (TypeError, ValueError):
        return None


def _parse_single_value_callback(data: str, prefix: str) -> str | None:
    try:
        actual, value = data.split(":", 1)
    except (AttributeError, ValueError):
        return None
    return value if actual == prefix and value else None


def _matching_local_tariffs(
    local_tariffs: list[dict[str, Any]],
    saas_tariff: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        tariff
        for tariff in local_tariffs
        if int(tariff.get("duration_days") or 0)
        == int(saas_tariff.get("duration_days") or 0)
        and float(tariff.get("price_rub") or 0)
        == float(saas_tariff.get("price_rub") or 0)
        and int(tariff.get("max_ips") or 0)
        == int(saas_tariff.get("device_limit") or 0)
        and int(tariff.get("traffic_limit_gb") or 0)
        == int(saas_tariff.get("traffic_limit_gb") or 0)
    ]


def _configured_projection_tariff_id() -> int | None:
    raw_value = os.getenv("WAVEMESH_SAAS_PROJECTION_TARIFF_ID")
    if raw_value is None or not raw_value.strip():
        return None
    try:
        tariff_id = int(raw_value)
    except ValueError as error:
        raise InternalApiError(
            "Configured SaaS projection tariff ID is invalid"
        ) from error
    if tariff_id < 1:
        raise InternalApiError(
            "Configured SaaS projection tariff ID is invalid"
        )
    return tariff_id


def _resolve_local_projection_tariffs(
    local_tariffs: list[dict[str, Any]],
    saas_tariff: dict[str, Any],
) -> list[dict[str, Any]]:
    exact_matches = _matching_local_tariffs(local_tariffs, saas_tariff)
    if exact_matches:
        return exact_matches

    configured_tariff_id = _configured_projection_tariff_id()
    if configured_tariff_id is None:
        return []

    return [
        tariff
        for tariff in local_tariffs
        if int(tariff.get("id") or 0) == configured_tariff_id
    ]


def _key_matches_material(key: dict[str, Any], material: dict[str, Any]) -> bool:
    return (
        key.get("panel_email") == material.get("panel_email")
        and key.get("client_uuid") == material.get("client_uuid")
        and key.get("sub_id") == material.get("sub_id")
        and int(key.get("panel_inbound_id") or 0)
        == int(material.get("primary_inbound_id") or 0)
    )


def _apply_replacement_material(key: dict[str, Any], material: dict[str, Any]) -> None:
    from database.requests import update_vpn_key_config

    server_id = key.get("server_id")
    if not server_id:
        raise InternalApiError("Local key has no server mapping")
    update_vpn_key_config(
        key_id=int(key["id"]),
        server_id=int(server_id),
        panel_inbound_id=int(material["primary_inbound_id"]),
        panel_email=str(material["panel_email"]),
        client_uuid=str(material["client_uuid"]),
        sub_id=str(material["sub_id"]),
    )


async def _render_saas_new_access_tariffs(
    target: Message,
    telegram_id: int,
) -> bool:
    """Render the authoritative SaaS tariff catalog for a Telegram user."""
    try:
        dashboard, tariffs = await internal_api_client.get_telegram_dashboard(
            telegram_id,
        ), await internal_api_client.list_tariffs()
    except InternalApiError as error:
        logger.warning(
            "SaaS new access catalog failed: telegram_id=%s code=%s status=%s",
            telegram_id,
            error.code,
            error.status,
        )
        await safe_edit_or_send(
            target,
            "❌ <b>Не удалось загрузить тарифы WaveMesh</b>\n\n"
            "Попробуйте немного позже.",
            force_new=True,
        )
        return False

    user = dashboard.get("user")
    if not isinstance(user, dict) or not user.get("user_id"):
        await safe_edit_or_send(
            target,
            "⏳ <b>Профиль WaveMesh ещё создаётся</b>\n\n"
            "Повторите команду /buy немного позже.",
            force_new=True,
        )
        return False

    available = [
        item
        for item in tariffs
        if isinstance(item, dict)
        and isinstance(item.get("tariff_id"), str)
        and isinstance(item.get("price_rub"), (int, float))
        and item["price_rub"] > 0
    ]
    builder = InlineKeyboardBuilder()
    for tariff in available:
        data = f"{_NEW_CHECKOUT_PREFIX}:{tariff['tariff_id']}"
        if len(data.encode("utf-8")) <= 64:
            builder.row(
                InlineKeyboardButton(
                    text=_tariff_button_text(tariff),
                    callback_data=data,
                )
            )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="home"))
    await safe_edit_or_send(
        target,
        "💳 <b>Купить новый ключ</b>\n\n"
        "Выберите тариф. Оплата и создание доступа выполняются через WaveMesh SaaS.",
        reply_markup=builder.as_markup(),
        force_new=True,
    )
    return True


@router.message(Command("buy"))
async def saas_buy_command(message: Message) -> None:
    """Open the authoritative SaaS catalog from the /buy command."""
    if message.from_user is None:
        return
    await _render_saas_new_access_tariffs(
        message,
        message.from_user.id,
    )


@router.callback_query(F.data == "buy_key")
async def saas_new_access_tariffs(callback: CallbackQuery) -> None:
    """Open the authoritative SaaS catalog from the main-page button."""
    rendered = await _render_saas_new_access_tariffs(
        callback.message,
        callback.from_user.id,
    )
    await callback.answer(
        "" if rendered else "Не удалось загрузить тарифы WaveMesh.",
        show_alert=not rendered,
    )


@router.callback_query(F.data.startswith(f"{_NEW_CHECKOUT_PREFIX}:"))
async def saas_new_access_checkout(callback: CallbackQuery) -> None:
    tariff_id = _parse_single_value_callback(callback.data, _NEW_CHECKOUT_PREFIX)
    if tariff_id is None:
        await callback.answer("Некорректный тариф.", show_alert=True)
        return
    try:
        dashboard = await internal_api_client.get_telegram_dashboard(callback.from_user.id)
        tariffs = await internal_api_client.list_tariffs()
        user = dashboard.get("user")
        user_id = user.get("user_id") if isinstance(user, dict) else None
        tariff = next(
            (
                item for item in tariffs
                if isinstance(item, dict) and item.get("tariff_id") == tariff_id
            ),
            None,
        )
        if not isinstance(user_id, str) or not isinstance(tariff, dict):
            raise InternalApiError("SaaS checkout context is invalid")
        result = await internal_api_client.create_order(
            user_id=user_id,
            tariff_id=tariff_id,
            access_id=None,
            idempotency_key=(
                f"telegram-new-access-{callback.from_user.id}-{tariff_id}-{callback.id}"
            ),
        )
    except InternalApiError as error:
        logger.warning(
            "SaaS new access checkout failed: telegram_id=%s tariff_id=%s code=%s status=%s",
            callback.from_user.id,
            tariff_id,
            error.code,
            error.status,
        )
        await callback.answer("Не удалось создать тестовый платёж.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Перейти к оплате", url=result["checkout_url"]))
    builder.row(
        InlineKeyboardButton(
            text="✅ Проверить оплату",
            callback_data=f"{_NEW_CHECK_PREFIX}:{result['order_id']}",
        )
    )
    builder.row(InlineKeyboardButton(text="⬅️ К тарифам", callback_data="buy_key"))
    await safe_edit_or_send(
        callback.message,
        (
            "✅ <b>Тестовый платёж создан</b>\n\n"
            f"🎫 {escape_html(str(tariff.get('name') or 'WaveMesh'))}\n\n"
            "Завершите оплату в YooKassa, вернитесь в бот и нажмите «Проверить оплату»."
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{_NEW_CHECK_PREFIX}:"))
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
                "⏳ <b>Оплата получена</b>\n\n"
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
                "⏳ <b>Оплата получена</b>\n\n"
                "Доступ сохранён в WaveMesh, но его пока не удалось показать. "
                "Повторите проверку позже."
            ),
            force_new=True,
        )


async def _load_checkout_context(
    callback: CallbackQuery,
    key_id: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None:
    """Validate local ownership and resolve one explicitly mapped SaaS access."""
    from database.requests import get_key_details_for_user

    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key:
        await callback.answer(
            "Ключ не найден или принадлежит другому пользователю.",
            show_alert=True,
        )
        return None

    try:
        dashboard = await internal_api_client.get_telegram_dashboard(
            callback.from_user.id,
        )
    except InternalApiError as error:
        logger.warning(
            "SaaS renewal dashboard lookup failed: telegram_id=%s key_id=%s "
            "code=%s status=%s retryable=%s",
            callback.from_user.id,
            key_id,
            error.code,
            error.status,
            error.retryable,
        )
        await callback.answer(
            "Не удалось получить данные WaveMesh. Попробуйте немного позже.",
            show_alert=True,
        )
        return None

    user = dashboard.get("user")
    user_id = user.get("user_id") if isinstance(user, dict) else None
    accesses = dashboard.get("accesses")
    valid_accesses = [
        access for access in accesses
        if isinstance(access, dict)
    ] if isinstance(accesses, list) else []
    matches = _matching_accesses(valid_accesses, key_id)

    if not isinstance(user_id, str) or not user_id:
        logger.error(
            "SaaS renewal dashboard has no user_id: telegram_id=%s key_id=%s",
            callback.from_user.id,
            key_id,
        )
        await callback.answer(
            "Профиль WaveMesh ещё не готов к оплате.",
            show_alert=True,
        )
        return None

    if len(matches) != 1:
        logger.warning(
            "SaaS renewal access mapping is ambiguous: telegram_id=%s "
            "key_id=%s accesses=%s matches=%s",
            callback.from_user.id,
            key_id,
            len(valid_accesses),
            len(matches),
        )
        await callback.answer(
            "Этот ключ ещё не сопоставлен с конкретным доступом в новом кабинете WaveMesh. Обратитесь в поддержку.",
            show_alert=True,
        )
        return None

    access_id = matches[0].get("access_id")
    if not isinstance(access_id, str) or not access_id:
        logger.error(
            "SaaS renewal mapped access has no access_id: telegram_id=%s key_id=%s",
            callback.from_user.id,
            key_id,
        )
        await callback.answer(
            "Сопоставление ключа в WaveMesh повреждено. Обратитесь в поддержку.",
            show_alert=True,
        )
        return None

    return key, {"user_id": user_id, "access": matches[0]}, dashboard


@router.callback_query(F.data.startswith("key_replace:"))
async def saas_replace_access(callback: CallbackQuery) -> None:
    """Replace one mapped access through the versioned Node Agent workflow."""
    try:
        key_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректный ключ.", show_alert=True)
        return

    context = await _load_checkout_context(callback, key_id)
    if context is None:
        return
    key, saas_context, _ = context
    if not key.get("is_active"):
        await callback.answer(
            "Срок действия ключа истёк. Сначала продлите его.",
            show_alert=True,
        )
        return

    access = saas_context["access"]
    access_id = access.get("access_id")
    if not isinstance(access_id, str) or not access_id:
        await callback.answer("Доступ WaveMesh не найден.", show_alert=True)
        return

    await callback.answer()
    await safe_edit_or_send(
        callback.message,
        "⏳ <b>Заменяем ключ</b>\n\nРабочий ключ останется активным до подтверждения нового.",
    )

    try:
        material = await internal_api_client.get_access_material(access_id)
        if material.get("ready") is True and not _key_matches_material(key, material):
            _apply_replacement_material(key, material)
        else:
            current_version = access.get("desired_version")
            if not isinstance(current_version, int) or current_version < 1:
                raise InternalApiError("SaaS access version is invalid")
            if access.get("status") == "materializing":
                target_version = current_version
            else:
                target_version = current_version + 1
                result = await internal_api_client.replace_access(
                    access_id=access_id,
                    idempotency_key=f"telegram-replace-{key_id}-{target_version}",
                )
                if result["desired_version"] != target_version:
                    raise InternalApiError("SaaS replacement version is invalid")

            material = {}
            for _ in range(45):
                material = await internal_api_client.get_access_material(access_id)
                if (
                    material.get("ready") is True
                    and material.get("desired_version") == target_version
                ):
                    break
                if material.get("status") == "failed":
                    raise InternalApiError("Access replacement failed", retryable=True)
                await asyncio.sleep(2)
            else:
                raise InternalApiError("Access replacement is still processing", retryable=True)
            _apply_replacement_material(key, material)

        from bot.keyboards.user import key_issued_kb
        from bot.utils.key_sender import send_key_with_qr
        from database.requests import get_key_details_for_user

        updated = get_key_details_for_user(key_id, callback.from_user.id)
        if not updated:
            raise InternalApiError("Updated local key projection is missing")
        await send_key_with_qr(callback, updated, key_issued_kb(), is_new=False)
    except InternalApiError as error:
        logger.warning(
            "SaaS access replacement failed: telegram_id=%s key_id=%s code=%s status=%s retryable=%s",
            callback.from_user.id,
            key_id,
            error.code,
            error.status,
            error.retryable,
        )
        await safe_edit_or_send(
            callback.message,
            "❌ <b>Замена пока не завершена</b>\n\nСтарый ключ сохранён и продолжает работать. Повторите позже.",
        )
    except Exception as error:  # noqa: BLE001 - Telegram handler boundary
        logger.exception(
            "Local replacement projection failed: telegram_id=%s key_id=%s code=%s",
            callback.from_user.id,
            key_id,
            type(error).__name__,
        )
        await safe_edit_or_send(
            callback.message,
            "❌ <b>Замена пока не завершена</b>\n\nНовый доступ сохранён в WaveMesh. Повторите замену, чтобы обновить ключ в боте.",
        )


@router.callback_query(F.data.startswith("key_renew:"))
async def saas_renew_select_tariff(callback: CallbackQuery) -> None:
    """Show the live SaaS tariff catalog for the selected mapped key."""
    try:
        key_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректный ключ.", show_alert=True)
        return

    context = await _load_checkout_context(callback, key_id)
    if context is None:
        return
    key, _, _ = context

    try:
        tariffs = await internal_api_client.list_tariffs()
    except InternalApiError as error:
        logger.warning(
            "SaaS tariff lookup failed: telegram_id=%s key_id=%s code=%s "
            "status=%s retryable=%s",
            callback.from_user.id,
            key_id,
            error.code,
            error.status,
            error.retryable,
        )
        await callback.answer(
            "Не удалось загрузить тарифы WaveMesh. Попробуйте позже.",
            show_alert=True,
        )
        return

    available = [
        tariff
        for tariff in tariffs
        if isinstance(tariff, dict)
        and isinstance(tariff.get("tariff_id"), str)
        and tariff.get("tariff_id")
        and isinstance(tariff.get("price_rub"), (int, float))
        and tariff.get("price_rub", 0) > 0
    ]
    if not available:
        await callback.answer(
            "Сейчас нет доступных тарифов для оплаты.",
            show_alert=True,
        )
        return

    builder = InlineKeyboardBuilder()
    rendered_tariffs = 0
    for tariff in available:
        callback_data = f"{_CALLBACK_PREFIX}:{key_id}:{tariff['tariff_id']}"
        if len(callback_data.encode("utf-8")) > 64:
            logger.error(
                "SaaS tariff callback exceeds Telegram limit: tariff_id=%s",
                tariff["tariff_id"],
            )
            continue
        builder.row(
            InlineKeyboardButton(
                text=_tariff_button_text(tariff),
                callback_data=callback_data,
            )
        )
        rendered_tariffs += 1

    if rendered_tariffs == 0:
        await callback.answer(
            "Тарифы временно невозможно показать в Telegram.",
            show_alert=True,
        )
        return

    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад к ключу",
            callback_data=f"key:{key_id}",
        )
    )

    text = (
        "💳 <b>Продление через WaveMesh</b>\n\n"
        f"🔑 Ключ: <b>{escape_html(key.get('display_name') or 'VPN-ключ')}</b>\n\n"
        "Выберите тариф. Заказ будет привязан именно к этому доступу в новом "
        "кабинете WaveMesh; локальная база бота и старый платёжный контур не используются."
    )
    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{_CALLBACK_PREFIX}:"))
async def saas_create_checkout(callback: CallbackQuery) -> None:
    """Create a SaaS order and display its external checkout URL."""
    parsed = _parse_checkout_callback(callback.data)
    if parsed is None:
        await callback.answer("Некорректные данные тарифа.", show_alert=True)
        return
    key_id, tariff_id = parsed

    context = await _load_checkout_context(callback, key_id)
    if context is None:
        return
    key, saas_context, _ = context

    try:
        tariffs = await internal_api_client.list_tariffs()
    except InternalApiError as error:
        logger.warning(
            "SaaS checkout tariff verification failed: telegram_id=%s "
            "key_id=%s code=%s status=%s",
            callback.from_user.id,
            key_id,
            error.code,
            error.status,
        )
        await callback.answer(
            "Не удалось проверить тариф. Попробуйте позже.",
            show_alert=True,
        )
        return

    tariff = next(
        (
            item
            for item in tariffs
            if isinstance(item, dict) and item.get("tariff_id") == tariff_id
        ),
        None,
    )
    if tariff is None:
        await callback.answer(
            "Выбранный тариф больше недоступен.",
            show_alert=True,
        )
        return

    access_id = saas_context["access"].get("access_id")
    await callback.answer("Создаём безопасную ссылку на оплату…")

    try:
        result = await internal_api_client.create_order(
            user_id=saas_context["user_id"],
            tariff_id=tariff_id,
            access_id=access_id,
            idempotency_key=(
                f"telegram-renew-{callback.from_user.id}-{key_id}-"
                f"{tariff_id}-{callback.id}"
            ),
        )
    except InternalApiError as error:
        logger.warning(
            "SaaS checkout creation failed: telegram_id=%s key_id=%s "
            "access_id=%s tariff_id=%s code=%s status=%s retryable=%s",
            callback.from_user.id,
            key_id,
            access_id,
            tariff_id,
            error.code,
            error.status,
            error.retryable,
        )
        if error.code == "COMMERCIAL_CUTOVER_DISABLED":
            message = (
                "Новый платёжный контур уже подключён в боте, но коммерческий "
                "gate на сервере WaveMesh пока выключен."
            )
        elif error.code == "ACCESS_BILLING_TARGET_NOT_READY":
            message = (
                "Ключ сопоставлен с новым кабинетом, но его платёжный доступ ещё "
                "не материализован в SaaS. Оплата не создана."
            )
        else:
            message = str(error) or "Не удалось создать платёж. Попробуйте позже."
        await safe_edit_or_send(
            callback.message,
            f"❌ <b>Не удалось создать оплату</b>\n\n{escape_html(message)}",
            reply_markup=(
                InlineKeyboardBuilder()
                .row(
                    InlineKeyboardButton(
                        text="⬅️ Вернуться к тарифам",
                        callback_data=f"key_renew:{key_id}",
                    )
                )
                .as_markup()
            ),
        )
        return

    checkout_url = result["checkout_url"]
    order_id = result["order_id"]
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💳 Перейти к оплате",
            url=checkout_url,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад к ключу",
            callback_data=f"key:{key_id}",
        )
    )

    logger.info(
        "SaaS checkout created: telegram_id=%s key_id=%s access_id=%s "
        "tariff_id=%s order_id=%s",
        callback.from_user.id,
        key_id,
        access_id,
        tariff_id,
        order_id,
    )

    await safe_edit_or_send(
        callback.message,
        (
            "✅ <b>Ссылка на оплату готова</b>\n\n"
            f"🔑 Ключ: <b>{escape_html(key.get('display_name') or 'VPN-ключ')}</b>\n"
            f"🎫 Тариф: <b>{escape_html(str(tariff.get('name') or 'WaveMesh'))}</b>\n\n"
            "Нажмите кнопку ниже. После подтверждения платежа будет продлён "
            "именно выбранный доступ."
        ),
        reply_markup=builder.as_markup(),
    )
