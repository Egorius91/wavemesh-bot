"""Telegram adapter for the durable SaaS trial; no local provisioning state."""

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.services.internal_api import InternalApiError, internal_api_client, validate_trial_user_id
from bot.services.runtime_mode import saas_client_mode_enabled
from bot.utils.text import safe_edit_or_send
from .payments.payment_return import process_ready_payment_return

router = Router()


def _buttons(*, activate: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if activate:
        rows.append([InlineKeyboardButton(text="Активировать пробный доступ", callback_data="trial_activate")])
    rows.extend([
        [InlineKeyboardButton(text="Проверить статус", callback_data="trial_status")],
        [InlineKeyboardButton(text="Мои ключи", callback_data="my_keys")],
        [InlineKeyboardButton(text="Помощь", callback_data="help"),
         InlineKeyboardButton(text="Главное меню", callback_data="home")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show(message: Message, telegram_id: int, *, activate: bool = False) -> None:
    # Material must never be posted to a group or a different user's chat.
    if not saas_client_mode_enabled() or message.chat.type != "private" or message.chat.id != telegram_id:
        return
    try:
        dashboard = await internal_api_client.get_telegram_dashboard(telegram_id)
        user = dashboard.get("user")
        user_id = validate_trial_user_id(user.get("user_id") if isinstance(user, dict) else None)
        if activate:
            trial = await internal_api_client.activate_trial(user_id)
        else:
            try:
                trial = await internal_api_client.get_trial(user_id)
            except InternalApiError as error:
                if error.status != 404:
                    raise
                await safe_edit_or_send(message,
                    "🎁 <b>Пробный доступ WaveMesh</b>\n\n"
                    "Активация общая для сайта и Telegram. Повторное открытие сохраняет тот же доступ и срок.",
                    reply_markup=_buttons(activate=True))
                return
        status = trial["status"]
        if status == "READY":
            # Shared delivery reloads the Telegram-owned dashboard before material.
            await process_ready_payment_return(message=message, telegram_id=telegram_id, access_id=trial["access_id"])
            return
        if status in {"PENDING", "MATERIALIZING"}:
            text = "⏳ <b>Пробный доступ готовится</b>\n\nПроверьте статус немного позже. Повторная активация не нужна."
        elif status in {"EXPIRED", "DISABLED"}:
            text = "Пробный доступ завершён или отключён. Вы можете продлить существующий доступ или обратиться за помощью."
        else:
            text = "Не удалось подготовить пробный доступ. Проверьте статус позже или обратитесь за помощью."
        await safe_edit_or_send(message, text, reply_markup=_buttons())
    except InternalApiError as error:
        if error.code == "LEGACY_TRIAL_RECONCILIATION_REQUIRED":
            text = "Ваш прежний пробный доступ требует проверки. Обратитесь за помощью; новая активация не требуется."
        elif error.code in {"MANAGED_TRIAL_PIPELINE_DISABLED", "COMMERCIAL_CUTOVER_DISABLED",
                            "TRIAL_OFFER_UNAVAILABLE", "TRIAL_TARIFF_UNAVAILABLE", "NO_COMMAND_READY_ENTRY_NODE"}:
            text = "Пробный доступ сейчас недоступен. Проверьте статус позже."
        elif activate:
            text = "Результат активации пока не подтверждён. Проверьте статус: если запрос выполнен, откроется тот же доступ."
        else:
            text = "Не удалось проверить пробный доступ. Повторите проверку позже."
        await safe_edit_or_send(message, text, reply_markup=_buttons())


@router.message(Command("trial"), StateFilter("*"))
async def trial_command(message: Message) -> None:
    if message.from_user:
        await _show(message, message.from_user.id)


@router.callback_query(F.data.in_({"trial_subscription", "trial_activate", "trial_status"}), StateFilter("*"))
async def trial_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _show(callback.message, callback.from_user.id, activate=callback.data == "trial_activate")
