"""Private admin entry points; Telegram/FSM state is never the operation journal."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.admin_provisioning import ProvisioningWorker
from bot.services.internal_api import internal_api_client
from bot.services.runtime_mode import saas_client_mode_enabled
from bot.utils.admin import is_admin
from bot.utils.text import safe_edit_or_send
from bot.states.admin_states import AdminStates
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


async def begin(callback, state, user):
    if not await allowed(callback):
        return
    await state.clear()
    await state.update_data(add_key_user_id=user["id"], add_key_user_telegram_id=user["telegram_id"])
    await state.set_state(AdminStates.add_key_server)
    await catalog_page(callback, state)


async def catalog_page(callback, state):
    if not await allowed(callback):
        return
    try:
        catalog = await internal_api_client.get_provisioning_entries()
        page = int(callback.data.split(":",1)[1]) if callback.data.startswith("admin_entry_page:") else 0
        if page < 0:
            raise ValueError()
        entries = catalog["entries"]
        buttons = [[InlineKeyboardButton(text=(e["name"] or e["external_id"])[:60],
            callback_data="admin_grant_entry:"+e["node_id"])] for e in entries[page*20:(page+1)*20]]
        if (page+1)*20 < len(entries):
            buttons.append([InlineKeyboardButton(text="Далее",callback_data=f"admin_entry_page:{page+1}")])
        if page:
            buttons.append([InlineKeyboardButton(text="Назад",callback_data=f"admin_entry_page:{page-1}")])
        await state.update_data(add_key_service_client_id=catalog["service_client_id"])
        await callback.answer()
        await safe_edit_or_send(callback.message, "Выберите Entry для нового доступа." if entries else "Сейчас нет доступных Entry. Попробуйте позже.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception:
        await callback.answer("Каталог Entry недоступен. Повторите позже.", show_alert=True)


async def select_entry(callback, state):
    if not await allowed(callback):
        return
    data = await state.get_data()
    if not data.get("add_key_user_id"):
        await callback.answer("Форма устарела. Откройте выдачу заново.", show_alert=True)
        return
    try:
        catalog = await internal_api_client.get_provisioning_entries()
        node_id = callback.data.split(":",1)[1]
        matches = [e for e in catalog["entries"] if e["node_id"] == node_id]
        if len(matches) != 1 or catalog["service_client_id"] != data.get("add_key_service_client_id"):
            raise ValueError()
        await state.update_data(add_key_node_id=node_id, add_key_node_name=matches[0]["name"])
        await state.set_state(AdminStates.add_key_traffic)
        await callback.answer()
        await safe_edit_or_send(callback.message, "Введите лимит трафика в ГБ (0 = без лимита):")
    except Exception:
        await callback.answer("Entry больше недоступен. Обновите выбор.", show_alert=True)


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
            catalog = await internal_api_client.get_provisioning_entries()
            if (catalog["service_client_id"] != data.get("add_key_service_client_id")
                    or data.get("add_key_node_id") not in [e["node_id"] for e in catalog["entries"]]):
                await callback.answer("Entry недоступен или выбор устарел. Откройте выдачу заново.", show_alert=True)
                return
            from database.requests import get_admin_tariff
            tariff = get_admin_tariff()
            row = journal.prepare(callback_key=callback_key, admin_id=callback.from_user.id, scope=scope,
                user_id=data["add_key_user_id"], telegram_id=data["add_key_user_telegram_id"],
                tariff_id=tariff["id"], days=data["add_key_days"],
                traffic_limit=data.get("add_key_traffic_gb", 0)*1024**3, device_limit=tariff.get("max_ips", 1),
                requested_node_id=data["add_key_node_id"])
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
