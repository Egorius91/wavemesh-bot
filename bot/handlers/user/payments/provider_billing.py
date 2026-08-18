"""Telegram user flow for provider-managed recurring billing agreements."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.internal_api import InternalApiError
from bot.services.provider_billing_api import (
    cancel_provider_billing_agreement,
    list_provider_billing_agreements,
)
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()

_BILLING_CALLBACK = "saas_billing"
_CONFIRM_PREFIX = "saas_billing_confirm"
_CANCEL_PREFIX = "saas_billing_cancel"

_STATUS_LABELS = {
    "pending": "ожидает первого платежа",
    "active": "включено",
    "past_due": "платёж требует внимания",
    "cancelled": "отключено",
    "expired": "завершено",
}


def _parse_agreement_callback(data: str | None, prefix: str) -> str | None:
    if not isinstance(data, str):
        return None
    try:
        actual, agreement_id = data.split(":", 1)
    except ValueError:
        return None
    if actual != prefix or not agreement_id:
        return None
    return agreement_id


def _is_cancellable(agreement: dict[str, Any]) -> bool:
    return agreement.get("status") not in {"cancelled", "expired"}


def _format_agreement(agreement: dict[str, Any]) -> str:
    provider = escape_html(str(agreement.get("provider") or "—"))
    status = _STATUS_LABELS.get(str(agreement.get("status")), "неизвестно")
    amount = agreement.get("amount_rub")
    currency = escape_html(str(agreement.get("currency") or "RUB"))
    amount_text = f"{amount:g} {currency}" if isinstance(amount, (int, float)) else currency
    requested = agreement.get("cancellation_requested_at")
    suffix = "\n⏳ Отключение уже запрошено." if requested else ""
    return f"<b>{provider}</b> · {escape_html(status)}\n{escape_html(amount_text)}{suffix}"


async def _render_provider_billing(
    target: Message,
    telegram_id: int,
    *,
    force_new: bool = False,
    notice: str | None = None,
) -> bool:
    try:
        agreements = await list_provider_billing_agreements(telegram_id)
    except InternalApiError as error:
        logger.warning(
            "Provider billing list failed: telegram_id=%s code=%s status=%s retryable=%s",
            telegram_id,
            error.code,
            error.status,
            error.retryable,
        )
        await safe_edit_or_send(
            target,
            "❌ <b>Не удалось загрузить автопродление</b>\n\nПопробуйте немного позже.",
            force_new=force_new,
        )
        return False

    lines = ["🔁 <b>Автопродление</b>"]
    if notice:
        lines.extend(["", notice])
    if agreements:
        for agreement in agreements:
            lines.extend(["", _format_agreement(agreement)])
    else:
        lines.extend(["", "Активных соглашений с платёжным провайдером нет."])

    lines.extend(
        [
            "",
            "Отключение автопродления не отключает уже оплаченный VPN-доступ.",
        ]
    )

    builder = InlineKeyboardBuilder()
    for agreement in agreements:
        if not _is_cancellable(agreement):
            continue
        agreement_id = str(agreement["agreement_id"])
        requested = bool(agreement.get("cancellation_requested_at"))
        prefix = _CANCEL_PREFIX if requested else _CONFIRM_PREFIX
        callback_data = f"{prefix}:{agreement_id}"
        if len(callback_data.encode("utf-8")) > 64:
            continue
        builder.row(
            InlineKeyboardButton(
                text=(
                    "🔄 Проверить отключение"
                    if requested
                    else "⛔ Отключить автопродление"
                ),
                callback_data=callback_data,
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ На главную", callback_data="start"))

    await safe_edit_or_send(
        target,
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        force_new=force_new,
    )
    return True


@router.message(Command("billing"))
async def provider_billing_command(message: Message) -> None:
    if message.from_user is None:
        return
    await _render_provider_billing(
        message,
        message.from_user.id,
        force_new=True,
    )


@router.callback_query(F.data == _BILLING_CALLBACK)
async def provider_billing_page(callback: CallbackQuery) -> None:
    rendered = await _render_provider_billing(
        callback.message,
        callback.from_user.id,
    )
    await callback.answer(
        "" if rendered else "Не удалось загрузить автопродление.",
        show_alert=not rendered,
    )


@router.callback_query(F.data.startswith(f"{_CONFIRM_PREFIX}:"))
async def provider_billing_confirm(callback: CallbackQuery) -> None:
    agreement_id = _parse_agreement_callback(callback.data, _CONFIRM_PREFIX)
    if agreement_id is None:
        await callback.answer("Некорректное соглашение.", show_alert=True)
        return

    try:
        agreements = await list_provider_billing_agreements(callback.from_user.id)
    except InternalApiError:
        await callback.answer("Не удалось проверить автопродление.", show_alert=True)
        return

    agreement = next(
        (
            item
            for item in agreements
            if item.get("agreement_id") == agreement_id
        ),
        None,
    )
    if not agreement or not _is_cancellable(agreement):
        await callback.answer("Автопродление уже завершено.", show_alert=True)
        await _render_provider_billing(callback.message, callback.from_user.id)
        return

    callback_data = f"{_CANCEL_PREFIX}:{agreement_id}"
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⛔ Подтвердить отключение",
            callback_data=callback_data,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=_BILLING_CALLBACK,
        )
    )
    await safe_edit_or_send(
        callback.message,
        (
            "⚠️ <b>Отключить автопродление?</b>\n\n"
            "Провайдер больше не должен выполнять будущие автоматические списания. "
            "Уже оплаченный VPN-доступ останется активным до конца оплаченного периода."
        ),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{_CANCEL_PREFIX}:"))
async def provider_billing_cancel(callback: CallbackQuery) -> None:
    agreement_id = _parse_agreement_callback(callback.data, _CANCEL_PREFIX)
    if agreement_id is None:
        await callback.answer("Некорректное соглашение.", show_alert=True)
        return

    try:
        result = await cancel_provider_billing_agreement(
            telegram_id=callback.from_user.id,
            agreement_id=agreement_id,
        )
    except InternalApiError as error:
        logger.warning(
            "Provider billing cancellation failed: telegram_id=%s agreement_id=%s code=%s status=%s retryable=%s",
            callback.from_user.id,
            agreement_id,
            error.code,
            error.status,
            error.retryable,
        )
        await callback.answer(
            "Не удалось подтвердить отключение. Повторная проверка использует тот же безопасный запрос.",
            show_alert=True,
        )
        return

    cancellation = result["cancellation"]
    if cancellation == "CONFIRMED":
        notice = "✅ Автопродление отключено у платёжного провайдера."
    elif cancellation == "NOT_REQUIRED":
        notice = "✅ Автопродление уже завершено."
    else:
        notice = "⏳ Запрос отправлен. Нажмите «Проверить отключение», чтобы сверить состояние провайдера."

    await callback.answer()
    await _render_provider_billing(
        callback.message,
        callback.from_user.id,
        notice=notice,
    )
