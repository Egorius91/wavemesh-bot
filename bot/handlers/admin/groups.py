"""
Роутер раздела «Группы тарифов».

Обрабатывает:
- Список групп
- Добавление группы с ручной позицией
- Переименование группы
- Изменение позиции группы
- Удаление группы (с переносом тарифов/серверов в «Основную»)
- Сортировку (⬆️ swap с предыдущей)
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.requests import (
    get_all_groups,
    get_group_by_id,
    add_group,
    update_group_name,
    update_group_sort_order,
    delete_group,
    move_group_up,
    get_tariffs_by_group,
    get_active_servers_by_group,
)
from bot.states.admin_states import AdminStates
from bot.utils.admin import is_admin
from bot.keyboards.admin import (
    groups_list_kb,
    group_view_kb,
    group_delete_confirm_kb,
    back_and_home_kb,
)
from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()


def _parse_position(raw: str) -> int | None:
    text = (raw or '').strip()
    if not text.isdigit():
        return None
    value = int(text)
    if not 1 <= value <= 9999:
        return None
    return value


def _build_groups_list_text(prefix: str = '') -> str:
    groups = get_all_groups()

    text = prefix
    text += (
        "📂 <b>Группы тарифов</b>\n\n"
        "Позиция группы влияет на порядок отображения тарифов на главной "
        "и в меню выбора тарифа при покупке.\n\n"
    )

    if len(groups) == 1:
        text += (
            "ℹ️ Сейчас одна группа — ограничения не действуют.\n"
            "Добавьте вторую группу, чтобы разделить тарифы и серверы.\n"
        )

    for group in groups:
        tariffs_count = len(get_tariffs_by_group(group['id']))
        servers_count = len(get_active_servers_by_group(group['id']))
        is_default = " _(по умолчанию)_" if group['id'] == 1 else ""
        text += f"\n{group['sort_order']}. 📂 <b>{group['name']}</b>{is_default}\n"
        text += f"   Тарифов: {tariffs_count} | Серверов: {servers_count}\n"

    return text


def _build_group_view_text(group_id: int, prefix: str = '') -> str:
    group = get_group_by_id(group_id)
    if not group:
        return "❌ Группа не найдена"

    tariffs = get_tariffs_by_group(group_id)
    servers = get_active_servers_by_group(group_id)
    is_default = " _(по умолчанию)_" if group_id == 1 else ""

    text = prefix
    text += (
        f"📂 <b>{group['name']}</b>{is_default}\n\n"
        f"🔢 Позиция: {group['sort_order']}\n"
        f"📋 Активных тарифов: {len(tariffs)}\n"
        f"🖥️ Активных серверов: {len(servers)}\n"
    )

    if tariffs:
        text += "\n<b>Тарифы:</b>\n"
        for t in tariffs:
            price_rub = t.get('price_rub')
            price = f"{price_rub} ₽" if price_rub else f"${(t['price_cents'] / 100):g}".replace('.', ',')
            text += f"  • {t['name']} — {price}\n"

    if servers:
        text += "\n<b>Серверы:</b>\n"
        for s in servers:
            text += f"  • {s['name']}\n"

    return text


# ============================================================================
# СПИСОК ГРУПП
# ============================================================================

@router.callback_query(F.data == "admin_groups")
async def show_groups_list(callback: CallbackQuery, state: FSMContext):
    """Показывает список групп тарифов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.payments_menu)
    groups = get_all_groups()

    await safe_edit_or_send(
        callback.message,
        _build_groups_list_text(),
        reply_markup=groups_list_kb(groups),
    )
    await callback.answer()


# ============================================================================
# ДОБАВЛЕНИЕ ГРУППЫ
# ============================================================================

@router.callback_query(F.data == "admin_group_add")
async def group_add_start(callback: CallbackQuery, state: FSMContext):
    """Начинает добавление новой группы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(AdminStates.group_add_name)
    await state.update_data(
        add_group_chat_id=callback.message.chat.id,
        add_group_message_id=callback.message.message_id,
    )

    await safe_edit_or_send(
        callback.message,
        "📂 <b>Новая группа</b>\n\n"
        "Введите название группы.\n\n"
        "Например: <b>Подписки</b> или <b>Разовые</b>\n\n"
        "Максимум 30 символов.",
        reply_markup=back_and_home_kb("admin_groups"),
    )
    await callback.answer()


@router.message(AdminStates.group_add_name)
async def group_add_name_handler(message: Message, state: FSMContext):
    """Обрабатывает ввод названия новой группы."""
    if not is_admin(message.from_user.id):
        return

    from bot.utils.text import get_message_text_for_storage

    name = get_message_text_for_storage(message, 'plain').strip()
    if not name or len(name) > 30:
        await safe_edit_or_send(message, "⚠️ Название должно быть от 1 до 30 символов.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    await state.update_data(new_group_name=name)
    await state.set_state(AdminStates.group_add_position)

    data = await state.get_data()
    add_chat_id = data.get('add_group_chat_id')
    add_msg_id = data.get('add_group_message_id')

    text = (
        f"📂 <b>Новая группа: {name}</b>\n\n"
        "Введите позицию группы числом.\n\n"
        "Чем меньше число, тем выше группа будет отображаться на главной "
        "и в меню покупки.\n\n"
        "Пример:\n"
        "• 10 — Подписки\n"
        "• 20 — Разовые\n\n"
        "Допустимо: от 1 до 9999."
    )

    if add_chat_id and add_msg_id:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=add_chat_id,
                message_id=add_msg_id,
                reply_markup=back_and_home_kb("admin_groups"),
            )
            return
        except Exception as e:
            logger.warning("Не удалось отредактировать сообщение добавления группы: %s", e)

    await safe_edit_or_send(message, text, reply_markup=back_and_home_kb("admin_groups"), force_new=True)


@router.message(AdminStates.group_add_position)
async def group_add_position_handler(message: Message, state: FSMContext):
    """Обрабатывает ввод позиции новой группы и создаёт группу."""
    if not is_admin(message.from_user.id):
        return

    from bot.utils.text import get_message_text_for_storage

    raw_position = get_message_text_for_storage(message, 'plain').strip()
    position = _parse_position(raw_position)
    if position is None:
        await safe_edit_or_send(message, "⚠️ Введите позицию числом от 1 до 9999.")
        return

    data = await state.get_data()
    name = data.get('new_group_name')
    add_chat_id = data.get('add_group_chat_id')
    add_msg_id = data.get('add_group_message_id')

    if not name:
        await state.clear()
        await safe_edit_or_send(message, "❌ Ошибка состояния. Начните создание группы заново.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    group_id = add_group(name, position)
    await state.set_state(AdminStates.payments_menu)

    groups = get_all_groups()
    text = _build_groups_list_text(f"✅ Группа <b>{name}</b> создана с позицией <b>{position}</b>.\n\n")

    if add_chat_id and add_msg_id:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=add_chat_id,
                message_id=add_msg_id,
                reply_markup=groups_list_kb(groups),
            )
            return
        except Exception as e:
            logger.warning("Не удалось отредактировать список групп: %s", e)

    await safe_edit_or_send(message, text, reply_markup=groups_list_kb(groups), force_new=True)


# ============================================================================
# ПРОСМОТР / РЕДАКТИРОВАНИЕ ГРУППЫ
# ============================================================================

@router.callback_query(F.data.startswith("admin_group_view:"))
async def group_view_handler(callback: CallbackQuery, state: FSMContext):
    """Показывает информацию о группе."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    group_id = int(callback.data.split(":")[1])
    group = get_group_by_id(group_id)
    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    await safe_edit_or_send(
        callback.message,
        _build_group_view_text(group_id),
        reply_markup=group_view_kb(group_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_group_edit:"))
async def group_edit_start(callback: CallbackQuery, state: FSMContext):
    """Начинает переименование группы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    group_id = int(callback.data.split(":")[1])
    group = get_group_by_id(group_id)
    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    await state.set_state(AdminStates.group_edit_name)
    await state.update_data(edit_group_id=group_id, edit_message_id=callback.message.message_id)

    await safe_edit_or_send(
        callback.message,
        f"✏️ <b>Переименование группы</b>\n\n"
        f"Текущее название: <b>{group['name']}</b>\n\n"
        "Введите новое название, максимум 30 символов:",
        reply_markup=back_and_home_kb(f"admin_group_view:{group_id}"),
    )
    await callback.answer()


@router.message(AdminStates.group_edit_name)
async def group_edit_name_handler(message: Message, state: FSMContext):
    """Обрабатывает ввод нового названия группы."""
    if not is_admin(message.from_user.id):
        return

    from bot.utils.text import get_message_text_for_storage

    name = get_message_text_for_storage(message, 'plain').strip()
    if not name or len(name) > 30:
        await safe_edit_or_send(message, "⚠️ Название должно быть от 1 до 30 символов.")
        return

    data = await state.get_data()
    group_id = data.get('edit_group_id')
    edit_msg_id = data.get('edit_message_id')
    if not group_id:
        await state.clear()
        await safe_edit_or_send(message, "❌ Ошибка состояния.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    success = update_group_name(group_id, name)
    await state.set_state(AdminStates.payments_menu)

    text = _build_group_view_text(group_id, "✅ Группа переименована.\n\n") if success else "❌ Не удалось переименовать группу."

    if edit_msg_id:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=message.chat.id,
                message_id=edit_msg_id,
                reply_markup=group_view_kb(group_id),
            )
            return
        except Exception:
            pass

    await safe_edit_or_send(message, text, reply_markup=group_view_kb(group_id), force_new=True)


@router.callback_query(F.data.startswith("admin_group_edit_position:"))
async def group_edit_position_start(callback: CallbackQuery, state: FSMContext):
    """Начинает изменение позиции группы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    group_id = int(callback.data.split(":")[1])
    group = get_group_by_id(group_id)
    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    await state.set_state(AdminStates.group_edit_position)
    await state.update_data(edit_group_id=group_id, edit_message_id=callback.message.message_id)

    await safe_edit_or_send(
        callback.message,
        f"🔢 <b>Позиция группы</b>\n\n"
        f"Группа: <b>{group['name']}</b>\n"
        f"Текущая позиция: <b>{group['sort_order']}</b>\n\n"
        "Введите новую позицию числом от 1 до 9999.\n\n"
        "Чем меньше число, тем выше группа будет отображаться.",
        reply_markup=back_and_home_kb(f"admin_group_view:{group_id}"),
    )
    await callback.answer()


@router.message(AdminStates.group_edit_position)
async def group_edit_position_handler(message: Message, state: FSMContext):
    """Обрабатывает ввод новой позиции группы."""
    if not is_admin(message.from_user.id):
        return

    from bot.utils.text import get_message_text_for_storage

    position = _parse_position(get_message_text_for_storage(message, 'plain'))
    if position is None:
        await safe_edit_or_send(message, "⚠️ Введите позицию числом от 1 до 9999.")
        return

    data = await state.get_data()
    group_id = data.get('edit_group_id')
    edit_msg_id = data.get('edit_message_id')
    if not group_id:
        await state.clear()
        await safe_edit_or_send(message, "❌ Ошибка состояния.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    success = update_group_sort_order(group_id, position)
    await state.set_state(AdminStates.payments_menu)

    text = _build_group_view_text(group_id, f"✅ Позиция группы изменена на <b>{position}</b>.\n\n") if success else "❌ Не удалось изменить позицию группы."

    if edit_msg_id:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=message.chat.id,
                message_id=edit_msg_id,
                reply_markup=group_view_kb(group_id),
            )
            return
        except Exception:
            pass

    await safe_edit_or_send(message, text, reply_markup=group_view_kb(group_id), force_new=True)


# ============================================================================
# УДАЛЕНИЕ ГРУППЫ
# ============================================================================

@router.callback_query(F.data.startswith("admin_group_delete:"))
async def group_delete_start(callback: CallbackQuery, state: FSMContext):
    """Подтверждение удаления группы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    group_id = int(callback.data.split(":")[1])
    if group_id == 1:
        await callback.answer("❌ Группу «Основная» нельзя удалить", show_alert=True)
        return

    group = get_group_by_id(group_id)
    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    tariffs = get_tariffs_by_group(group_id)
    servers = get_active_servers_by_group(group_id)

    text = (
        f"⚠️ <b>Удаление группы «{group['name']}»</b>\n\n"
        f"📋 Тарифов: {len(tariffs)}\n"
        f"🖥️ Серверов: {len(servers)}\n\n"
    )
    if tariffs or servers:
        text += "❗ Все тарифы и серверы будут перенесены в группу «Основная».\n\n"
    text += "Вы уверены?"

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=group_delete_confirm_kb(group_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_group_delete_confirm:"))
async def group_delete_confirm(callback: CallbackQuery, state: FSMContext):
    """Выполняет удаление группы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    group_id = int(callback.data.split(":")[1])
    success = delete_group(group_id)
    if success:
        await callback.answer("✅ Группа удалена, содержимое перенесено в «Основная»")
    else:
        await callback.answer("❌ Не удалось удалить группу", show_alert=True)

    await show_groups_list(callback, state)


# ============================================================================
# СОРТИРОВКА ГРУПП (⬆️)
# ============================================================================

@router.callback_query(F.data.startswith("admin_group_up:"))
async def group_move_up_handler(callback: CallbackQuery, state: FSMContext):
    """Поднимает группу вверх в сортировке."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    group_id = int(callback.data.split(":")[1])
    move_group_up(group_id)
    await callback.answer("🔄 Порядок обновлён")
    await show_groups_list(callback, state)
