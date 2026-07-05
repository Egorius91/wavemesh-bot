"""
Роутер управления тарифами.

Обрабатывает:
- Список тарифов
- Добавление тарифа (пошаговый диалог)
- Просмотр тарифа
- Редактирование (листание параметров)
- Скрытие/показ (soft delete)
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database.requests import (
    get_all_tariffs,
    get_tariff_by_id,
    add_tariff,
    update_tariff_field,
    toggle_tariff_active,
    get_groups_count,
    get_all_groups,
    get_group_by_id,
    update_tariff,
)
from bot.utils.admin import is_admin
from bot.states.admin_states import (
    AdminStates,
    TARIFF_PARAMS,
    get_tariff_param_by_index,
    get_tariff_params_list,
    get_total_tariff_params,
)
from bot.keyboards.admin import (
    tariffs_list_kb,
    tariff_view_kb,
    add_tariff_step_kb,
    add_tariff_confirm_kb,
    edit_tariff_kb,
    back_and_home_kb,
    group_select_kb,
)

logger = logging.getLogger(__name__)

from bot.utils.text import safe_edit_or_send

router = Router()


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================


def _billing_type_label(value: str) -> str:
    return "Подписка с автопродлением" if value == "recurring" else "Разовая покупка"


def _billing_type_kb(back_callback: str = "admin_tariff_add_back"):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🧾 Разовая покупка", callback_data="admin_tariff_billing:one_time"),
    )
    builder.row(
        InlineKeyboardButton(text="🔁 Подписка с автопродлением", callback_data="admin_tariff_billing:recurring"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback))
    return builder.as_markup()


def _edit_billing_type_kb(current_param: int, total: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🧾 Разовая покупка", callback_data="admin_tariff_edit_billing:one_time"),
    )
    builder.row(
        InlineKeyboardButton(text="🔁 Подписка с автопродлением", callback_data="admin_tariff_edit_billing:recurring"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️", callback_data="admin_tariff_edit_prev"),
        InlineKeyboardButton(text=f"{current_param + 1}/{total}", callback_data="noop"),
        InlineKeyboardButton(text="▶️", callback_data="admin_tariff_edit_next"),
    )
    builder.row(
        InlineKeyboardButton(text="✅ Готово", callback_data="admin_tariff_edit_done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_tariff_edit_cancel"),
    )
    return builder.as_markup()


def format_tariff_value(param: dict, value) -> str:
    """Форматирует значение параметра для отображения."""
    if value is None:
        return "—"
    if param.get('key') == 'billing_type':
        return _billing_type_label(value)
    if 'format' in param:
        return param['format'](value)
    return str(value)


# ============================================================================
# СПИСОК ТАРИФОВ
# ============================================================================

@router.callback_query(F.data == "admin_tariffs")
async def show_tariffs_list(callback: CallbackQuery, state: FSMContext):
    """Показывает список тарифов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.tariffs_list)
    await state.update_data(tariff_data={})
    
    tariffs = get_all_tariffs(include_hidden=True)
    
    if not tariffs:
        text = (
            "📋 <b>Тарифы</b>\n\n"
            "Тарифов пока нет.\n"
            "Нажмите «➕ Добавить тариф» чтобы создать первый!"
        )
    else:
        lines = ["📋 <b>Тарифы</b>\n"]
        for tariff in tariffs:
            status = "🟢" if tariff['is_active'] else "🔴"
            price_usd = tariff['price_cents'] / 100
            price_str = f"{price_usd:g}".replace('.', ',')
            traffic_gb = tariff.get('traffic_limit_gb', 0)
            traffic_text = f"{traffic_gb} ГБ" if traffic_gb > 0 else "Безлим"
            billing_icon = "🔁" if tariff.get('billing_type') == 'recurring' or tariff.get('is_recurring') else "🧾"
            lines.append(
                f"{status} {billing_icon} <b>{tariff['name']}</b> — "
                f"${price_str} / ⭐ {tariff['price_stars']} / ₽ {tariff.get('price_rub', 0)} / "
                f"{tariff['duration_days']} дн. / {traffic_text}"
            )
        text = "\n".join(lines)
    
    await safe_edit_or_send(callback.message, text, reply_markup=tariffs_list_kb(tariffs))
    await callback.answer()


async def render_tariff_view(message: Message, tariff_id: int, state: FSMContext):
    """Отрисовывает экран просмотра тарифа."""
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        return
    
    await state.set_state(AdminStates.tariff_view)
    await state.update_data(tariff_id=tariff_id)
    
    status_emoji = "🟢 Активен" if tariff['is_active'] else "🔴 Скрыт"
    price_usd = tariff['price_cents'] / 100
    price_str = f"{price_usd:g}".replace('.', ',')
    billing_type = tariff.get('billing_type') or ('recurring' if tariff.get('is_recurring') else 'one_time')
    
    lines = [
        f"📋 <b>{tariff['name']}</b>\n",
        f"💰 Цена (USDT): <code>${price_str}</code>",
        f"⭐ Цена (Stars): <code>{tariff['price_stars']}</code>",
        f"💳 Цена (₽): <code>{tariff.get('price_rub', 0)}</code>",
        f"📅 Длительность: <code>{tariff['duration_days']} дней</code>",
        f"🔁 Тип оплаты: <code>{_billing_type_label(billing_type)}</code>",
    ]
    
    traffic_gb = tariff.get('traffic_limit_gb', 0)
    traffic_text = f"{traffic_gb} ГБ" if traffic_gb > 0 else "Безлимит"
    lines.append(f"📦 Лимит трафика: <code>{traffic_text}</code>")
    
    max_ips = tariff.get('max_ips', 1)
    lines.append(f"💻 Лимит устройств: <code>{max_ips} устр.</code>")
    
    groups_count = get_groups_count()
    if groups_count > 1:
        group = get_group_by_id(tariff.get('group_id', 1))
        group_name = group['name'] if group else 'Основная'
        lines.append(f"📂 Группа: <code>{group_name}</code>")
    
    lines.extend([
        f"📊 Порядок: <code>{tariff.get('display_order', 0)}</code>",
        f"\n{status_emoji}",
    ])
    
    await safe_edit_or_send(
        message,
        "\n".join(lines),
        reply_markup=tariff_view_kb(tariff_id, tariff['is_active'], groups_count > 1),
    )


# ============================================================================
# ПРОСМОТР ТАРИФА
# ============================================================================

@router.callback_query(F.data.startswith("admin_tariff_view:"))
async def show_tariff_view(callback: CallbackQuery, state: FSMContext):
    """Показывает детали тарифа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    tariff_id = int(callback.data.split(":")[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return
    
    await render_tariff_view(callback.message, tariff_id, state)
    await callback.answer()


# ============================================================================
# СКРЫТИЕ/ПОКАЗ ТАРИФА
# ============================================================================

@router.callback_query(F.data.startswith("admin_tariff_toggle:"))
async def toggle_tariff(callback: CallbackQuery, state: FSMContext):
    """Переключает видимость тарифа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    tariff_id = int(callback.data.split(":")[1])
    new_status = toggle_tariff_active(tariff_id)
    if new_status is None:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return
    
    status_text = "показан 👁️" if new_status else "скрыт 👁️‍🗨️"
    await callback.answer(f"Тариф {status_text}")
    await render_tariff_view(callback.message, tariff_id, state)


# ============================================================================
# ДОБАВЛЕНИЕ ТАРИФА
# ============================================================================

ADD_TARIFF_STATES = [
    AdminStates.add_tariff_name,
    AdminStates.add_tariff_price_cents,
    AdminStates.add_tariff_price_stars,
    AdminStates.add_tariff_price_rub,
    AdminStates.add_tariff_duration,
    AdminStates.add_tariff_traffic_limit,
    AdminStates.add_tariff_max_ips,
    AdminStates.add_tariff_billing_type,
]


def _add_params() -> list:
    return [p for p in get_tariff_params_list() if p['key'] != 'display_order']


def get_add_step_state(step: int) -> AdminStates:
    """Возвращает состояние для шага добавления."""
    params = _add_params()
    if step <= 0:
        return ADD_TARIFF_STATES[0]
    if step > len(params):
        return AdminStates.add_tariff_confirm
    
    key = params[step - 1]['key']
    state_map = {
        'name': AdminStates.add_tariff_name,
        'price_cents': AdminStates.add_tariff_price_cents,
        'price_stars': AdminStates.add_tariff_price_stars,
        'price_rub': AdminStates.add_tariff_price_rub,
        'duration_days': AdminStates.add_tariff_duration,
        'traffic_limit_gb': AdminStates.add_tariff_traffic_limit,
        'max_ips': AdminStates.add_tariff_max_ips,
        'billing_type': AdminStates.add_tariff_billing_type,
    }
    return state_map.get(key, AdminStates.add_tariff_confirm)


def get_add_step_text(step: int, data: dict) -> str:
    """Формирует текст для шага добавления тарифа."""
    params = _add_params()
    total = len(params)
    if step > total:
        return "Ошибка"
    
    param = params[step - 1]
    lines = [f"📝 <b>Добавление тарифа ({step}/{total})</b>\n"]
    
    for i in range(step - 1):
        p = params[i]
        value = data.get(p['key'], '—')
        display = format_tariff_value(p, value)
        lines.append(f"✅ {p['label']}: <code>{display}</code>")
    
    if step > 1:
        lines.append("")
    
    if param['key'] == 'billing_type':
        lines.append("Выберите <b>тип оплаты</b>:")
        lines.append("_Разовая покупка или подписка с автоматическим продлением через ЮKassa._")
    else:
        lines.append(f"Введите <b>{param['label'].lower()}</b>:")
        lines.append(f"_({param['hint']})_")
    
    if param.get('help'):
        lines.append(f"\n{param['help']}")
    
    return "\n".join(lines)


async def _render_add_step(message, state: FSMContext, step: int, data: dict, force_new: bool = False):
    params = _add_params()
    total = len(params)
    text = get_add_step_text(step, data)
    param = params[step - 1]
    if param['key'] == 'billing_type':
        reply_markup = _billing_type_kb()
    else:
        reply_markup = add_tariff_step_kb(step, total)
    await safe_edit_or_send(message, text, reply_markup=reply_markup, force_new=force_new)


async def _show_add_confirm(message, state: FSMContext, tariff_data: dict, force_new: bool = True):
    await state.set_state(AdminStates.add_tariff_confirm)
    price_usd = tariff_data['price_cents'] / 100
    price_str = f"{price_usd:g}".replace('.', ',')
    billing_type = tariff_data.get('billing_type', 'one_time')
    lines = [
        "✅ <b>Все данные введены!</b>\n",
        f"📌 Название: <code>{tariff_data['name']}</code>",
        f"💰 Цена (USDT): <code>${price_str}</code>",
        f"⭐ Цена (Stars): <code>{tariff_data['price_stars']}</code>",
        f"💳 Цена (₽): <code>{tariff_data.get('price_rub', 0)}</code>",
        f"📅 Длительность: <code>{tariff_data['duration_days']} дней</code>",
        f"🔁 Тип оплаты: <code>{_billing_type_label(billing_type)}</code>",
    ]
    traffic_gb = tariff_data.get('traffic_limit_gb', 0)
    traffic_text = f"{traffic_gb} ГБ" if traffic_gb > 0 else "Безлимит"
    lines.append(f"📦 Лимит трафика: <code>{traffic_text}</code>")
    max_ips = tariff_data.get('max_ips', 1)
    lines.append(f"💻 Лимит устройств: <code>{max_ips} устр.</code>")
    lines.append("\nСохранить тариф?")
    await safe_edit_or_send(message, "\n".join(lines), reply_markup=add_tariff_confirm_kb(), force_new=force_new)


@router.callback_query(F.data == "admin_tariff_add")
async def start_add_tariff(callback: CallbackQuery, state: FSMContext):
    """Начинает диалог добавления тарифа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    groups_count = get_groups_count()
    if groups_count > 1:
        groups = get_all_groups()
        await state.set_state(AdminStates.tariff_select_group)
        await state.update_data(tariff_data={})
        await safe_edit_or_send(
            callback.message,
            "📝 <b>Добавление тарифа</b>\n\nВыберите группу для нового тарифа:",
            reply_markup=group_select_kb(groups, "tariff_group_select", "admin_tariffs"),
        )
        await callback.answer()
        return
    
    await state.set_state(AdminStates.add_tariff_name)
    await state.update_data(tariff_data={}, add_step=1, selected_group_id=1)
    await _render_add_step(callback.message, state, 1, {})
    await callback.answer()


@router.callback_query(AdminStates.tariff_select_group, F.data.startswith("tariff_group_select:"))
async def tariff_group_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора группы для нового тарифа."""
    group_id = int(callback.data.split(":")[1])
    await state.set_state(AdminStates.add_tariff_name)
    await state.update_data(add_step=1, selected_group_id=group_id)
    group = get_group_by_id(group_id)
    group_name = group['name'] if group else 'Основная'
    text = f"📂 Группа: <b>{group_name}</b>\n\n" + get_add_step_text(1, {})
    total = len(_add_params())
    await safe_edit_or_send(callback.message, text, reply_markup=add_tariff_step_kb(1, total))
    await callback.answer()


@router.callback_query(F.data == "admin_tariff_add_back")
async def add_tariff_back(callback: CallbackQuery, state: FSMContext):
    """Возврат на предыдущий шаг добавления."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = await state.get_data()
    current_step = data.get('add_step', 1)
    if current_step <= 1:
        await show_tariffs_list(callback, state)
        return
    
    new_step = current_step - 1
    new_state = get_add_step_state(new_step)
    await state.set_state(new_state)
    await state.update_data(add_step=new_step)
    await _render_add_step(callback.message, state, new_step, data.get('tariff_data', {}))
    await callback.answer()


async def process_add_tariff_step(message: Message, state: FSMContext):
    """Обрабатывает ввод на шаге добавления тарифа."""
    data = await state.get_data()
    current_step = data.get('add_step', 1)
    tariff_data = data.get('tariff_data', {})
    params = _add_params()
    total = len(params)
    if current_step > total:
        return
    
    from bot.utils.text import get_message_text_for_storage, safe_edit_or_send
    param = params[current_step - 1]
    if param['key'] == 'billing_type':
        await safe_edit_or_send(message, "Выберите тип оплаты кнопкой ниже.")
        return

    value = get_message_text_for_storage(message, 'plain')
    if not param['validate'](value):
        await safe_edit_or_send(message, f"❌ {param['error']}\n\nПопробуйте ещё раз:")
        return
    if 'convert' in param:
        value = param['convert'](value)
    tariff_data[param['key']] = value
    await state.update_data(tariff_data=tariff_data)
    try:
        await message.delete()
    except Exception:
        pass
    
    if current_step < total:
        new_step = current_step + 1
        new_state = get_add_step_state(new_step)
        await state.set_state(new_state)
        await state.update_data(add_step=new_step)
        await _render_add_step(message, state, new_step, tariff_data, force_new=True)
    else:
        await _show_add_confirm(message, state, tariff_data, force_new=True)


@router.callback_query(AdminStates.add_tariff_billing_type, F.data.startswith("admin_tariff_billing:"))
async def add_tariff_billing_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа оплаты тарифа."""
    billing_type = callback.data.split(":", 1)[1]
    if billing_type not in ("one_time", "recurring"):
        await callback.answer("❌ Некорректный тип", show_alert=True)
        return
    data = await state.get_data()
    tariff_data = data.get('tariff_data', {})
    tariff_data['billing_type'] = billing_type
    tariff_data['is_recurring'] = 1 if billing_type == 'recurring' else 0
    tariff_data['billing_period_days'] = tariff_data.get('duration_days', 0)
    await state.update_data(tariff_data=tariff_data)
    await _show_add_confirm(callback.message, state, tariff_data, force_new=False)
    await callback.answer("✅ Тип оплаты выбран")


# Хендлеры для каждого состояния добавления
@router.message(AdminStates.add_tariff_name)
async def add_tariff_name_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


@router.message(AdminStates.add_tariff_price_cents)
async def add_tariff_price_cents_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


@router.message(AdminStates.add_tariff_price_stars)
async def add_tariff_price_stars_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


@router.message(AdminStates.add_tariff_price_rub)
async def add_tariff_price_rub_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


@router.message(AdminStates.add_tariff_duration)
async def add_tariff_duration_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


@router.message(AdminStates.add_tariff_traffic_limit)
async def add_tariff_traffic_limit_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


@router.message(AdminStates.add_tariff_max_ips)
async def add_tariff_max_ips_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


@router.message(AdminStates.add_tariff_billing_type)
async def add_tariff_billing_type_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


@router.callback_query(F.data == "admin_tariff_add_save")
async def add_tariff_save(callback: CallbackQuery, state: FSMContext):
    """Сохраняет новый тариф."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = await state.get_data()
    tariff_data = data.get('tariff_data', {})
    try:
        selected_group_id = data.get('selected_group_id', 1)
        billing_type = tariff_data.get('billing_type', 'one_time')
        tariff_id = add_tariff(
            name=tariff_data['name'],
            duration_days=tariff_data['duration_days'],
            price_cents=tariff_data['price_cents'],
            price_stars=tariff_data['price_stars'],
            price_rub=tariff_data.get('price_rub', 0),
            display_order=0,
            traffic_limit_gb=tariff_data.get('traffic_limit_gb', 0),
            group_id=selected_group_id,
            max_ips=tariff_data.get('max_ips', 1),
            billing_type=billing_type,
            is_recurring=1 if billing_type == 'recurring' else 0,
            billing_period_days=tariff_data.get('billing_period_days') or tariff_data['duration_days'],
            recurring_provider='yookassa_qr',
        )
        await safe_edit_or_send(callback.message, f"✅ <b>Тариф успешно добавлен!</b>\n\n📋 {tariff_data['name']}")
        await callback.answer("✅ Тариф добавлен!")
        await render_tariff_view(callback.message, tariff_id, state)
    except Exception as e:
        logger.error(f"Ошибка добавления тарифа: {e}")
        await safe_edit_or_send(
            callback.message,
            f"❌ <b>Ошибка сохранения</b>\n\n<code>{e}</code>",
            reply_markup=back_and_home_kb("admin_tariffs"),
        )
        await callback.answer("❌ Ошибка", show_alert=True)


# ============================================================================
# РЕДАКТИРОВАНИЕ ТАРИФА
# ============================================================================

def get_edit_tariff_text(tariff: dict, current_param: int) -> str:
    """Формирует текст для экрана редактирования тарифа."""
    params = get_tariff_params_list()
    total = len(params)
    param = params[current_param]
    current_value = tariff.get(param['key'])
    display_value = format_tariff_value(param, current_value)
    lines = [
        f"✏️ <b>Редактирование: {tariff['name']}</b> ({current_param + 1}/{total})\n",
        f"📌 Параметр: <b>{param['label']}</b>",
        f"📝 Текущее значение: <code>{display_value}</code>\n",
    ]
    if param['key'] == 'billing_type':
        lines.append("Выберите новое значение кнопкой:")
    else:
        lines.append("Введите новое значение или используйте кнопки навигации:")
        lines.append(f"_({param['hint']})_")
    if param.get('help'):
        lines.append(f"\n{param['help']}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("admin_tariff_edit:"))
async def start_edit_tariff(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование тарифа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    tariff_id = int(callback.data.split(":")[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return
    
    await state.set_state(AdminStates.edit_tariff)
    await state.update_data(tariff_id=tariff_id, edit_param=0)
    text = get_edit_tariff_text(tariff, 0)
    total = get_total_tariff_params()
    await safe_edit_or_send(callback.message, text, reply_markup=edit_tariff_kb(0, total))
    await callback.answer()


@router.callback_query(F.data == "admin_tariff_edit_prev")
async def edit_tariff_prev(callback: CallbackQuery, state: FSMContext):
    """Предыдущий параметр при редактировании."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    current_param = data.get('edit_param', 0)
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return
    
    new_param = max(0, current_param - 1)
    await state.update_data(edit_param=new_param)
    await _render_edit_param(callback.message, tariff, new_param)
    await callback.answer()


@router.callback_query(F.data == "admin_tariff_edit_next")
async def edit_tariff_next(callback: CallbackQuery, state: FSMContext):
    """Следующий параметр при редактировании."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    current_param = data.get('edit_param', 0)
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return
    
    total = get_total_tariff_params()
    new_param = min(total - 1, current_param + 1)
    await state.update_data(edit_param=new_param)
    await _render_edit_param(callback.message, tariff, new_param)
    await callback.answer()


async def _render_edit_param(message, tariff: dict, current_param: int):
    text = get_edit_tariff_text(tariff, current_param)
    total = get_total_tariff_params()
    param = get_tariff_param_by_index(current_param)
    if param['key'] == 'billing_type':
        markup = _edit_billing_type_kb(current_param, total)
    else:
        markup = edit_tariff_kb(current_param, total)
    await safe_edit_or_send(message, text, reply_markup=markup)


@router.callback_query(AdminStates.edit_tariff, F.data.startswith("admin_tariff_edit_billing:"))
async def edit_tariff_billing_type(callback: CallbackQuery, state: FSMContext):
    """Редактирует тип оплаты тарифа кнопкой."""
    billing_type = callback.data.split(":", 1)[1]
    if billing_type not in ("one_time", "recurring"):
        await callback.answer("❌ Некорректный тип", show_alert=True)
        return
    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    current_param = data.get('edit_param', 0)
    update_tariff(
        tariff_id,
        billing_type=billing_type,
        is_recurring=1 if billing_type == 'recurring' else 0,
    )
    tariff = get_tariff_by_id(tariff_id)
    await callback.answer("✅ Тип оплаты обновлён")
    await _render_edit_param(callback.message, tariff, current_param)


@router.message(AdminStates.edit_tariff)
async def edit_tariff_value(message: Message, state: FSMContext):
    """Обрабатывает ввод нового значения при редактировании."""
    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    current_param = data.get('edit_param', 0)
    from bot.utils.text import get_message_text_for_storage, safe_edit_or_send
    param = get_tariff_param_by_index(current_param)
    if param['key'] == 'billing_type':
        await safe_edit_or_send(message, "Выберите тип оплаты кнопкой в сообщении редактирования.")
        return
    value = get_message_text_for_storage(message, 'plain')
    if not param['validate'](value):
        await safe_edit_or_send(message, f"❌ {param['error']}")
        return
    if 'convert' in param:
        value = param['convert'](value)
    success = update_tariff_field(tariff_id, param['key'], value)
    if not success:
        await safe_edit_or_send(message, "❌ Ошибка сохранения")
        return
    try:
        await message.delete()
    except Exception:
        pass
    tariff = get_tariff_by_id(tariff_id)
    text = get_edit_tariff_text(tariff, current_param)
    total = get_total_tariff_params()
    await safe_edit_or_send(
        message,
        f"✅ <b>{param['label']}</b> обновлено!\n\n" + text,
        reply_markup=edit_tariff_kb(current_param, total),
        force_new=True,
    )


@router.callback_query(F.data == "admin_tariff_edit_done")
async def edit_tariff_done(callback: CallbackQuery, state: FSMContext):
    """Завершение редактирования — возврат к просмотру."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    await render_tariff_view(callback.message, tariff_id, state)


@router.callback_query(F.data == "admin_tariff_edit_cancel")
async def edit_tariff_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования — возврат к просмотру."""
    await edit_tariff_done(callback, state)


# ============================================================================
# ИЗМЕНЕНИЕ ГРУППЫ ТАРИФА
# ============================================================================

@router.callback_query(F.data.startswith("admin_tariff_change_group:"))
async def tariff_change_group_start(callback: CallbackQuery, state: FSMContext):
    """Показывает список групп для смены группы тарифа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    tariff_id = int(callback.data.split(":")[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return
    
    groups = get_all_groups()
    await safe_edit_or_send(
        callback.message,
        f"📂 <b>Смена группы тарифа «{tariff['name']}»</b>\n\nВыберите новую группу:",
        reply_markup=group_select_kb(groups, "tariff_group_change", f"admin_tariff_view:{tariff_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tariff_group_change:"))
async def tariff_change_group_execute(callback: CallbackQuery, state: FSMContext):
    """Меняет группу тарифа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    
    new_group_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    if not tariff_id:
        await callback.answer("❌ Ошибка состояния", show_alert=True)
        return
    
    update_tariff(tariff_id, group_id=new_group_id)
    group = get_group_by_id(new_group_id)
    group_name = group['name'] if group else 'Основная'
    await callback.answer(f"✅ Группа изменена на «{group_name}»")
    await render_tariff_view(callback.message, tariff_id, state)
