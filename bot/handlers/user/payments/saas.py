"""SaaS checkout flow for Telegram renewals.

This router is included only in WaveMesh SaaS client mode and is registered
before legacy payment routers. It performs read-only ownership checks against
the local key projection, then creates the commercial order exclusively in the
WaveMesh SaaS Internal API for the exact mapped access.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.internal_api import (
    InternalApiError,
    internal_api_client,
)
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

_CALLBACK_PREFIX = "saas_checkout"


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
