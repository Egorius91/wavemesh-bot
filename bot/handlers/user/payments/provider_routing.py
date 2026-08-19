"""Explicit payment-provider selection for the authoritative SaaS checkout flow.

This router is registered before the existing SaaS checkout router. It only
intercepts tariff checkout callbacks. A single selectable provider preserves
the existing provider-omitted DEFAULT route; multiple providers require an
explicit user choice and are revalidated immediately before order creation.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.user.payments import saas
from bot.services.internal_api import InternalApiError, internal_api_client
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

_NEW_PROVIDER_PREFIX = "saas_np"
_RENEW_PROVIDER_PREFIX = "saas_rp"
_PROVIDER_BY_ALIAS = {
    "yk": "YOOKASSA",
    "pg": "PLATEGA",
}
_ALIAS_BY_PROVIDER = {provider: alias for alias, provider in _PROVIDER_BY_ALIAS.items()}
_PROVIDER_LABELS = {
    "YOOKASSA": "ЮKassa",
    "PLATEGA": "Platega",
}


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider)


def _provider_alias(provider: str) -> str | None:
    return _ALIAS_BY_PROVIDER.get(provider)


def _parse_new_provider_callback(data: str) -> tuple[str, str] | None:
    try:
        prefix, alias, tariff_id = data.split(":", 2)
    except (AttributeError, ValueError):
        return None
    provider = _PROVIDER_BY_ALIAS.get(alias)
    if prefix != _NEW_PROVIDER_PREFIX or provider is None or not tariff_id:
        return None
    return provider, tariff_id


def _parse_renew_provider_callback(data: str) -> tuple[int, str, str] | None:
    try:
        prefix, raw_key_id, alias, tariff_id = data.split(":", 3)
        provider = _PROVIDER_BY_ALIAS.get(alias)
        if prefix != _RENEW_PROVIDER_PREFIX or provider is None or not tariff_id:
            return None
        return int(raw_key_id), provider, tariff_id
    except (AttributeError, TypeError, ValueError):
        return None


def _provider_names(options: list[dict[str, str]]) -> list[str]:
    return [option["provider"] for option in options]


def _find_tariff(tariffs: Any, tariff_id: str) -> dict[str, Any] | None:
    if not isinstance(tariffs, list):
        return None
    return next(
        (
            item
            for item in tariffs
            if isinstance(item, dict) and item.get("tariff_id") == tariff_id
        ),
        None,
    )


def _billing_mode(tariff: dict[str, Any]) -> str | None:
    value = tariff.get("billing_mode")
    return value if value in {"ONE_TIME", "RECURRING"} else None


def _provider_keyboard(
    providers: list[str],
    callback_data: callable,
    *,
    back_text: str,
    back_callback: str,
) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for provider in providers:
        alias = _provider_alias(provider)
        if alias is None:
            continue
        data = callback_data(alias)
        if len(data.encode("utf-8")) > 64:
            logger.error(
                "SaaS provider callback exceeds Telegram limit: provider=%s",
                provider,
            )
            continue
        builder.row(
            InlineKeyboardButton(
                text=_provider_label(provider),
                callback_data=data,
            )
        )
    builder.row(
        InlineKeyboardButton(
            text=back_text,
            callback_data=back_callback,
        )
    )
    return builder


async def _load_new_context(
    callback: CallbackQuery,
    tariff_id: str,
) -> tuple[str, dict[str, Any], str] | None:
    try:
        dashboard = await internal_api_client.get_telegram_dashboard(
            callback.from_user.id,
        )
        tariffs = await internal_api_client.list_tariffs()
    except InternalApiError as error:
        logger.warning(
            "SaaS new checkout context failed: telegram_id=%s tariff_id=%s "
            "code=%s status=%s",
            callback.from_user.id,
            tariff_id,
            error.code,
            error.status,
        )
        await callback.answer("Не удалось проверить тариф. Попробуйте позже.", show_alert=True)
        return None

    user = dashboard.get("user") if isinstance(dashboard, dict) else None
    user_id = user.get("user_id") if isinstance(user, dict) else None
    tariff = _find_tariff(tariffs, tariff_id)
    billing_mode = _billing_mode(tariff) if tariff is not None else None
    if not isinstance(user_id, str) or not user_id or tariff is None or billing_mode is None:
        await callback.answer("Выбранный тариф больше недоступен.", show_alert=True)
        return None
    return user_id, tariff, billing_mode


async def _load_renew_context(
    callback: CallbackQuery,
    key_id: int,
    tariff_id: str,
) -> tuple[dict[str, Any], dict[str, Any], str, str] | None:
    context = await saas._load_checkout_context(callback, key_id)
    if context is None:
        return None
    key, saas_context, _ = context

    try:
        tariffs = await internal_api_client.list_tariffs()
    except InternalApiError as error:
        logger.warning(
            "SaaS renewal provider routing tariff lookup failed: "
            "telegram_id=%s key_id=%s tariff_id=%s code=%s status=%s",
            callback.from_user.id,
            key_id,
            tariff_id,
            error.code,
            error.status,
        )
        await callback.answer("Не удалось проверить тариф. Попробуйте позже.", show_alert=True)
        return None

    tariff = _find_tariff(tariffs, tariff_id)
    billing_mode = _billing_mode(tariff) if tariff is not None else None
    access_id = saas_context["access"].get("access_id")
    if (
        tariff is None
        or billing_mode is None
        or not isinstance(access_id, str)
        or not access_id
    ):
        await callback.answer("Выбранный тариф или доступ больше недоступен.", show_alert=True)
        return None
    return key, tariff, billing_mode, access_id


async def _load_provider_names(
    callback: CallbackQuery,
    billing_mode: str,
) -> list[str] | None:
    try:
        options = await internal_api_client.list_payment_providers(billing_mode)
    except InternalApiError as error:
        logger.warning(
            "SaaS payment provider catalog failed: telegram_id=%s billing_mode=%s "
            "code=%s status=%s retryable=%s",
            callback.from_user.id,
            billing_mode,
            error.code,
            error.status,
            error.retryable,
        )
        await callback.answer(
            "Не удалось загрузить способы оплаты. Попробуйте позже.",
            show_alert=True,
        )
        return None

    providers = _provider_names(options)
    if not providers:
        await callback.answer(
            "Для этого тарифа сейчас нет доступных способов оплаты.",
            show_alert=True,
        )
        return None
    return providers


async def _create_new_order(
    callback: CallbackQuery,
    *,
    user_id: str,
    tariff: dict[str, Any],
    billing_mode: str,
    provider: str | None,
) -> None:
    tariff_id = str(tariff["tariff_id"])
    try:
        result = await internal_api_client.create_order(
            user_id=user_id,
            tariff_id=tariff_id,
            billing_mode=billing_mode,
            provider=provider,
            access_id=None,
            idempotency_key=(
                f"telegram-new-access-{callback.from_user.id}-{tariff_id}-"
                f"{provider or 'default'}-{callback.id}"
            ),
        )
    except InternalApiError as error:
        logger.warning(
            "SaaS new access checkout failed: telegram_id=%s tariff_id=%s "
            "provider=%s code=%s status=%s retryable=%s",
            callback.from_user.id,
            tariff_id,
            provider or "DEFAULT",
            error.code,
            error.status,
            error.retryable,
        )
        await callback.answer("Не удалось создать оплату.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💳 Перейти к оплате",
            url=result["checkout_url"],
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Проверить оплату",
            callback_data=f"{saas._NEW_CHECK_PREFIX}:{result['order_id']}",
        )
    )
    builder.row(InlineKeyboardButton(text="⬅️ К тарифам", callback_data="buy_key"))
    provider_line = (
        f"💳 Способ оплаты: <b>{escape_html(_provider_label(provider))}</b>\n"
        if provider
        else ""
    )
    await safe_edit_or_send(
        callback.message,
        (
            "✅ <b>Ссылка на оплату готова</b>\n\n"
            f"🎫 {escape_html(str(tariff.get('name') or 'WaveMesh'))}\n"
            f"{provider_line}\n"
            "Завершите оплату, вернитесь в бот и нажмите «Проверить оплату»."
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


async def _create_renew_order(
    callback: CallbackQuery,
    *,
    key_id: int,
    key: dict[str, Any],
    tariff: dict[str, Any],
    billing_mode: str,
    access_id: str,
    provider: str | None,
) -> None:
    tariff_id = str(tariff["tariff_id"])
    await callback.answer("Создаём безопасную ссылку на оплату…")
    context = await saas._load_checkout_context(callback, key_id)
    if context is None:
        return
    _, saas_context, _ = context

    try:
        result = await internal_api_client.create_order(
            user_id=saas_context["user_id"],
            tariff_id=tariff_id,
            billing_mode=billing_mode,
            provider=provider,
            access_id=access_id,
            idempotency_key=(
                f"telegram-renew-{callback.from_user.id}-{key_id}-{tariff_id}-"
                f"{provider or 'default'}-{callback.id}"
            ),
        )
    except InternalApiError as error:
        logger.warning(
            "SaaS checkout creation failed: telegram_id=%s key_id=%s "
            "access_id=%s tariff_id=%s provider=%s code=%s status=%s retryable=%s",
            callback.from_user.id,
            key_id,
            access_id,
            tariff_id,
            provider or "DEFAULT",
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
        elif error.code in {
            "PAYMENT_PROVIDER_DISABLED",
            "PAYMENT_PROVIDER_NOT_CONFIGURED",
            "PAYMENT_PROVIDER_UNAVAILABLE",
        }:
            message = "Выбранный способ оплаты сейчас недоступен. Оплата не создана."
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

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💳 Перейти к оплате",
            url=result["checkout_url"],
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
        "tariff_id=%s provider=%s order_id=%s",
        callback.from_user.id,
        key_id,
        access_id,
        tariff_id,
        provider or "DEFAULT",
        result["order_id"],
    )
    provider_line = (
        f"💳 Способ оплаты: <b>{escape_html(_provider_label(provider))}</b>\n"
        if provider
        else ""
    )
    await safe_edit_or_send(
        callback.message,
        (
            "✅ <b>Ссылка на оплату готова</b>\n\n"
            f"🔑 Ключ: <b>{escape_html(key.get('display_name') or 'VPN-ключ')}</b>\n"
            f"🎫 Тариф: <b>{escape_html(str(tariff.get('name') or 'WaveMesh'))}</b>\n"
            f"{provider_line}\n"
            "Нажмите кнопку ниже. После подтверждения платежа будет продлён "
            "именно выбранный доступ."
        ),
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith(f"{saas._NEW_CHECKOUT_PREFIX}:"))
async def route_new_checkout(callback: CallbackQuery) -> None:
    tariff_id = saas._parse_single_value_callback(
        callback.data,
        saas._NEW_CHECKOUT_PREFIX,
    )
    if tariff_id is None:
        await callback.answer("Некорректный тариф.", show_alert=True)
        return

    context = await _load_new_context(callback, tariff_id)
    if context is None:
        return
    user_id, tariff, billing_mode = context
    providers = await _load_provider_names(callback, billing_mode)
    if providers is None:
        return
    if len(providers) == 1:
        await _create_new_order(
            callback,
            user_id=user_id,
            tariff=tariff,
            billing_mode=billing_mode,
            provider=None,
        )
        return

    builder = _provider_keyboard(
        providers,
        lambda alias: f"{_NEW_PROVIDER_PREFIX}:{alias}:{tariff_id}",
        back_text="⬅️ К тарифам",
        back_callback="buy_key",
    )
    await safe_edit_or_send(
        callback.message,
        (
            "💳 <b>Выберите способ оплаты</b>\n\n"
            f"🎫 {escape_html(str(tariff.get('name') or 'WaveMesh'))}"
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{_NEW_PROVIDER_PREFIX}:"))
async def create_new_checkout_with_provider(callback: CallbackQuery) -> None:
    parsed = _parse_new_provider_callback(callback.data)
    if parsed is None:
        await callback.answer("Некорректный способ оплаты.", show_alert=True)
        return
    provider, tariff_id = parsed

    context = await _load_new_context(callback, tariff_id)
    if context is None:
        return
    user_id, tariff, billing_mode = context
    providers = await _load_provider_names(callback, billing_mode)
    if providers is None:
        return
    if provider not in providers:
        await callback.answer(
            "Выбранный способ оплаты больше недоступен.",
            show_alert=True,
        )
        return

    await _create_new_order(
        callback,
        user_id=user_id,
        tariff=tariff,
        billing_mode=billing_mode,
        provider=provider,
    )


@router.callback_query(F.data.startswith(f"{saas._CALLBACK_PREFIX}:"))
async def route_renew_checkout(callback: CallbackQuery) -> None:
    parsed = saas._parse_checkout_callback(callback.data)
    if parsed is None:
        await callback.answer("Некорректные данные тарифа.", show_alert=True)
        return
    key_id, tariff_id = parsed

    context = await _load_renew_context(callback, key_id, tariff_id)
    if context is None:
        return
    key, tariff, billing_mode, access_id = context
    providers = await _load_provider_names(callback, billing_mode)
    if providers is None:
        return
    if len(providers) == 1:
        await _create_renew_order(
            callback,
            key_id=key_id,
            key=key,
            tariff=tariff,
            billing_mode=billing_mode,
            access_id=access_id,
            provider=None,
        )
        return

    builder = _provider_keyboard(
        providers,
        lambda alias: f"{_RENEW_PROVIDER_PREFIX}:{key_id}:{alias}:{tariff_id}",
        back_text="⬅️ Вернуться к тарифам",
        back_callback=f"key_renew:{key_id}",
    )
    await safe_edit_or_send(
        callback.message,
        (
            "💳 <b>Выберите способ оплаты</b>\n\n"
            f"🔑 Ключ: <b>{escape_html(key.get('display_name') or 'VPN-ключ')}</b>\n"
            f"🎫 Тариф: <b>{escape_html(str(tariff.get('name') or 'WaveMesh'))}</b>"
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{_RENEW_PROVIDER_PREFIX}:"))
async def create_renew_checkout_with_provider(callback: CallbackQuery) -> None:
    parsed = _parse_renew_provider_callback(callback.data)
    if parsed is None:
        await callback.answer("Некорректный способ оплаты.", show_alert=True)
        return
    key_id, provider, tariff_id = parsed

    context = await _load_renew_context(callback, key_id, tariff_id)
    if context is None:
        return
    key, tariff, billing_mode, access_id = context
    providers = await _load_provider_names(callback, billing_mode)
    if providers is None:
        return
    if provider not in providers:
        await callback.answer(
            "Выбранный способ оплаты больше недоступен.",
            show_alert=True,
        )
        return

    await _create_renew_order(
        callback,
        key_id=key_id,
        key=key,
        tariff=tariff,
        billing_mode=billing_mode,
        access_id=access_id,
        provider=provider,
    )
