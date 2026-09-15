"""Private admin entry points; Telegram/FSM state is never the operation journal."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.admin_provisioning import ProvisioningWorker
from bot.services.internal_api import internal_api_client
from bot.services.runtime_mode import saas_client_mode_enabled
from bot.utils.admin import is_admin
from bot.utils.text import safe_edit_or_send
from database.admin_provisioning import Journal, JournalConflict, connection_scope


async def allowed(callback):
    if (not is_admin(callback.from_user.id) or not saas_client_mode_enabled()
            or callback.message is None or callback.message.chat.type != "private"
            or callback.message.chat.id != callback.from_user.id):
        await callback.answer("Действие недоступно", show_alert=True)
        return False
    return True


async def show(callback, row):
    messages = {
        "DONE": "✅ Конфигурация подтверждена SaaS и сохранена в существующем ключе.",
        "PENDING": "⏳ Выдача сохранена. Бот продолжит обработку после перезапуска.",
        "FAILED": "⚠️ SaaS сообщил об остановке выдачи. Требуется проверка прежней операции.",
        "TIMEOUT": "⚠️ Подтверждение задерживается. Сверка проверит прежнюю операцию без новой выдачи.",
        "MANUAL_REVIEW": "⚠️ Автоматическая обработка остановлена. Нужна проверка привязки или результата операции.",
    }
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Проверить / сверить", callback_data="admin_grant_reconcile:"+row["id"])],
        [InlineKeyboardButton(text="К пользователю", callback_data=f"admin_user_view:{row['telegram_id']}")],
    ])
    await safe_edit_or_send(callback.message, messages[row["status"]], reply_markup=keyboard)


async def confirm(callback, state):
    if not await allowed(callback):
        return
    journal = Journal()
    scope = connection_scope(internal_api_client)
    callback_key = f"{callback.from_user.id}:{callback.message.chat.id}:{callback.message.message_id}"
    try:
        row = journal.for_callback(callback_key, callback.from_user.id, scope)
        if not row:
            data = await state.get_data()
            if not data.get("add_key_user_id") or not data.get("add_key_days"):
                await callback.answer("Форма устарела. Откройте выдачу из карточки пользователя.", show_alert=True)
                return
            from database.requests import get_admin_tariff
            tariff = get_admin_tariff()
            row = journal.prepare(callback_key=callback_key, admin_id=callback.from_user.id, scope=scope,
                user_id=data["add_key_user_id"], telegram_id=data["add_key_user_telegram_id"],
                tariff_id=tariff["id"], days=data["add_key_days"],
                traffic_limit=data.get("add_key_traffic_gb", 0)*1024**3, device_limit=tariff.get("max_ips", 1))
    except JournalConflict:
        await callback.answer("Выдача требует сверки: проверьте прежнюю операцию и владельца.", show_alert=True)
        return
    except Exception:
        await callback.answer("Не удалось проверить сохранение операции. Повторите эту же кнопку.", show_alert=True)
        return
    await callback.answer("Операция сохранена")
    await show(callback, row)


async def reconcile(callback):
    if not await allowed(callback):
        return
    journal = Journal()
    operation_id = callback.data.split(":", 1)[1]
    row = journal.get(operation_id)
    if not row or row["admin_id"] != callback.from_user.id:
        await callback.answer("Операция недоступна", show_alert=True)
        return
    await callback.answer("Проверяем прежнюю операцию")
    row = await ProvisioningWorker(internal_api_client, journal).reconcile(operation_id, explicit=True)
    await show(callback, row)
