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
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.requests import (
    get_all_tariffs,
    get_tariff_by_id,
    add_tariff,
    update_tariff_field,
    update_tariff,
    toggle_tariff_active,
    get_groups_count,
    get_all_groups,
    get_group_by_id,
)
from bot.utils.admin import is_admin
from bot.states.admin_states import (
    AdminStates,
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
from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================


def _is_recurring(tariff_or_data: dict) -> bool:
    return tariff_or_data.get('billing_type') == 'recurring' or bool(tariff_or_data.get('is_recurring'))


def _tariff_type_label(tariff_or_data: dict) -> str:
    return '🔁 Подписка с автосписанием' if _is_recurring(tariff_or_data) else '🧾 Разовая покупка'


def _get_add_params() -> list:
    return [p for p in get_tariff_params_list() if p['key'] != 'display_order']


def format_tariff_value(param: dict, value) -> str:
    """Форматирует значение параметра для отображения."""
    if value is None:
        return '—'
    if 'format' in param:
        return param['format'](value)
    return str(value)


# ============================================================================
# СПИСОК ТАРИФОВ
# ============================================================================


@router.callback_query(F.data == 'admin_tariffs')
async def show_tariffs_list(callback: CallbackQuery, state: FSMContext):
    """Показывает список тарифов."""
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    await state.set_state(AdminStates.tariffs_list)
    await state.update_data(tariff_data={})

    tariffs = get_all_tariffs(include_hidden=True)

    if not tariffs:
        text = (
            '📋 <b>Тарифы</b>\n\n'
            'Тарифов пока нет.\n'
            'Нажмите «➕ Добавить тариф» чтобы создать первый!'
        )
    else:
        lines = ['📋 <b>Тарифы</b>\n']
        for tariff in tariffs:
            status = '🟢' if tariff['is_active'] else '🔴'
            type_icon = '🔁' if _is_recurring(tariff) else '🧾'
            price_usd = tariff['price_cents'] / 100
            price_str = f'{price_usd:g}'.replace('.', ',')
            traffic_gb = tariff.get('traffic_limit_gb', 0)
            traffic_text = f'{traffic_gb} ГБ' if traffic_gb > 0 else 'Безлим'
            period_text = f"каждые {tariff.get('billing_period_days') or tariff['duration_days']} дн." if _is_recurring(tariff) else f"{tariff['duration_days']} дн."
            lines.append(
                f"{status} {type_icon} <b>{tariff['name']}</b> — "
                f"${price_str} / ⭐ {tariff['price_stars']} / ₽ {tariff.get('price_rub', 0)} / "
                f"{period_text} / {traffic_text}"
            )
        text = '\n'.join(lines)

    await safe_edit_or_send(callback.message, text, reply_markup=tariffs_list_kb(tariffs))
    await callback.answer()


async def render_tariff_view(message: Message, tariff_id: int, state: FSMContext):
    """Отрисовывает экран просмотра тарифа."""
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        return

    await state.set_state(AdminStates.tariff_view)
    await state.update_data(tariff_id=tariff_id)

    status_emoji = '🟢 Активен' if tariff['is_active'] else '🔴 Скрыт'
    price_usd = tariff['price_cents'] / 100
    price_str = f'{price_usd:g}'.replace('.', ',')
    recurring = _is_recurring(tariff)
    period = tariff.get('billing_period_days') or tariff['duration_days']

    lines = [
        f"📋 <b>{tariff['name']}</b>\n",
        f"{_tariff_type_label(tariff)}",
        f"💰 Цена (USDT): <code>${price_str}</code>",
        f"⭐ Цена (Stars): <code>{tariff['price_stars']}</code>",
        f"💳 Цена (₽): <code>{tariff.get('price_rub', 0)}</code>",
    ]

    if recurring:
        lines.append(f"📅 Период списания: <code>каждые {period} дней</code>")
        lines.append('🏦 Провайдер автосписания: <code>ЮKassa API</code>')
    else:
        lines.append(f"📅 Длительность: <code>{tariff['duration_days']} дней</code>")

    traffic_gb = tariff.get('traffic_limit_gb', 0)
    traffic_text = f'{traffic_gb} ГБ' if traffic_gb > 0 else 'Безлимит'
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
        '\n'.join(lines),
        reply_markup=tariff_view_kb(tariff_id, tariff['is_active'], groups_count > 1),
    )


# ============================================================================
# ПРОСМОТР/СКРЫТИЕ
# ============================================================================


@router.callback_query(F.data.startswith('admin_tariff_view:'))
async def show_tariff_view(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    tariff_id = int(callback.data.split(':')[1])
    if not get_tariff_by_id(tariff_id):
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return

    await render_tariff_view(callback.message, tariff_id, state)
    await callback.answer()


@router.callback_query(F.data.startswith('admin_tariff_toggle:'))
async def toggle_tariff(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    tariff_id = int(callback.data.split(':')[1])
    new_status = toggle_tariff_active(tariff_id)
    if new_status is None:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return

    status_text = 'показан 👁️' if new_status else 'скрыт 👁️‍🗨️'
    await callback.answer(f'Тариф {status_text}')
    await render_tariff_view(callback.message, tariff_id, state)


# ============================================================================
# ДОБАВЛЕНИЕ ТАРИФА
# ============================================================================


ADD_TARIFF_STATES = [
    AdminStates.add_tariff_billing_type,
    AdminStates.add_tariff_name,
    AdminStates.add_tariff_price_cents,
    AdminStates.add_tariff_price_stars,
    AdminStates.add_tariff_price_rub,
    AdminStates.add_tariff_duration,
    AdminStates.add_tariff_traffic_limit,
    AdminStates.add_tariff_max_ips,
]


def get_add_step_state(step: int) -> AdminStates:
    params = _get_add_params()
    if step <= 0:
        return ADD_TARIFF_STATES[0]
    if step > len(params):
        return AdminStates.add_tariff_confirm

    key = params[step - 1]['key']
    state_map = {
        'billing_type': AdminStates.add_tariff_billing_type,
        'name': AdminStates.add_tariff_name,
        'price_cents': AdminStates.add_tariff_price_cents,
        'price_stars': AdminStates.add_tariff_price_stars,
        'price_rub': AdminStates.add_tariff_price_rub,
        'duration_days': AdminStates.add_tariff_duration,
        'traffic_limit_gb': AdminStates.add_tariff_traffic_limit,
        'max_ips': AdminStates.add_tariff_max_ips,
    }
    return state_map.get(key, AdminStates.add_tariff_confirm)


def get_add_step_text(step: int, data: dict) -> str:
    params = _get_add_params()
    total = len(params)
    if step > total:
        return 'Ошибка'

    param = params[step - 1]
    lines = [f'📝 <b>Добавление тарифа ({step}/{total})</b>\n']

    for i in range(step - 1):
        p = params[i]
        value = data.get(p['key'], '—')
        display = format_tariff_value(p, value)
        lines.append(f"✅ {p['label']}: <code>{display}</code>")

    if step > 1:
        lines.append('')

    label = param['label'].lower()
    if param['key'] == 'duration_days' and data.get('billing_type') == 'recurring':
        label = 'период автосписания в днях'

    lines.append(f'Введите <b>{label}</b>:')
    lines.append(f"_({param['hint']})_")
    if param.get('help'):
        lines.append(f"\n{param['help']}")
    return '\n'.join(lines)


@router.callback_query(F.data == 'admin_tariff_add')
async def start_add_tariff(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    groups_count = get_groups_count()
    if groups_count > 1:
        groups = get_all_groups()
        await state.set_state(AdminStates.tariff_select_group)
        await state.update_data(tariff_data={})
        await safe_edit_or_send(
            callback.message,
            '📝 <b>Добавление тарифа</b>\n\nВыберите группу для нового тарифа:',
            reply_markup=group_select_kb(groups, 'tariff_group_select', 'admin_tariffs'),
        )
        await callback.answer()
        return

    await state.set_state(AdminStates.add_tariff_billing_type)
    await state.update_data(tariff_data={}, add_step=1, selected_group_id=1)
    total = len(_get_add_params())
    await safe_edit_or_send(callback.message, get_add_step_text(1, {}), reply_markup=add_tariff_step_kb(1, total))
    await callback.answer()


@router.callback_query(AdminStates.tariff_select_group, F.data.startswith('tariff_group_select:'))
async def tariff_group_selected(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(':')[1])
    await state.set_state(AdminStates.add_tariff_billing_type)
    await state.update_data(tariff_data={}, add_step=1, selected_group_id=group_id)

    group = get_group_by_id(group_id)
    group_name = group['name'] if group else 'Основная'
    total = len(_get_add_params())
    text = f'📂 Группа: <b>{group_name}</b>\n\n' + get_add_step_text(1, {})
    await safe_edit_or_send(callback.message, text, reply_markup=add_tariff_step_kb(1, total))
    await callback.answer()


@router.callback_query(F.data == 'admin_tariff_add_back')
async def add_tariff_back(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    data = await state.get_data()
    current_step = data.get('add_step', 1)
    if current_step <= 1:
        await show_tariffs_list(callback, state)
        return

    new_step = current_step - 1
    await state.set_state(get_add_step_state(new_step))
    await state.update_data(add_step=new_step)
    total = len(_get_add_params())
    await safe_edit_or_send(
        callback.message,
        get_add_step_text(new_step, data.get('tariff_data', {})),
        reply_markup=add_tariff_step_kb(new_step, total),
    )
    await callback.answer()


async def process_add_tariff_step(message: Message, state: FSMContext):
    data = await state.get_data()
    current_step = data.get('add_step', 1)
    tariff_data = data.get('tariff_data', {})
    params = _get_add_params()
    total = len(params)
    if current_step > total:
        return

    from bot.utils.text import get_message_text_for_storage
    param = params[current_step - 1]
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
        await state.set_state(get_add_step_state(new_step))
        await state.update_data(add_step=new_step)
        await safe_edit_or_send(
            message,
            get_add_step_text(new_step, tariff_data),
            reply_markup=add_tariff_step_kb(new_step, total),
            force_new=True,
        )
        return

    await state.set_state(AdminStates.add_tariff_confirm)
    price_usd = tariff_data['price_cents'] / 100
    price_str = f'{price_usd:g}'.replace('.', ',')
    recurring = tariff_data.get('billing_type') == 'recurring'

    lines = [
        '✅ <b>Все данные введены!</b>\n',
        f"{_tariff_type_label(tariff_data)}",
        f"📌 Название: <code>{tariff_data['name']}</code>",
        f"💰 Цена (USDT): <code>${price_str}</code>",
        f"⭐ Цена (Stars): <code>{tariff_data['price_stars']}</code>",
        f"💳 Цена (₽): <code>{tariff_data.get('price_rub', 0)}</code>",
    ]

    if recurring:
        lines.append(f"📅 Период списания: <code>каждые {tariff_data['duration_days']} дней</code>")
        lines.append('🏦 Автосписание: <code>ЮKassa API</code>')
        if int(tariff_data.get('price_rub') or 0) <= 0:
            lines.append('\n⚠️ <b>Для подписки цена в рублях должна быть больше 0.</b>')
    else:
        lines.append(f"📅 Длительность: <code>{tariff_data['duration_days']} дней</code>")

    traffic_gb = tariff_data.get('traffic_limit_gb', 0)
    traffic_text = f'{traffic_gb} ГБ' if traffic_gb > 0 else 'Безлимит'
    lines.append(f"📦 Лимит трафика: <code>{traffic_text}</code>")
    lines.append(f"💻 Лимит устройств: <code>{tariff_data.get('max_ips', 1)} устр.</code>")
    lines.append('\nСохранить тариф?')

    await safe_edit_or_send(message, '\n'.join(lines), reply_markup=add_tariff_confirm_kb(), force_new=True)


@router.message(AdminStates.add_tariff_billing_type)
async def add_tariff_billing_type_handler(message: Message, state: FSMContext):
    await process_add_tariff_step(message, state)


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


@router.callback_query(F.data == 'admin_tariff_add_save')
async def add_tariff_save(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    data = await state.get_data()
    tariff_data = data.get('tariff_data', {})

    try:
        billing_type = tariff_data.get('billing_type', 'one_time')
        if billing_type == 'recurring' and int(tariff_data.get('price_rub') or 0) <= 0:
            await callback.answer('❌ Для подписки нужна цена в рублях больше 0', show_alert=True)
            return

        selected_group_id = data.get('selected_group_id', 1)
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
            billing_period_days=tariff_data['duration_days'],
            recurring_provider='yookassa_qr',
        )

        await safe_edit_or_send(
            callback.message,
            f"✅ <b>Тариф успешно добавлен!</b>\n\n📋 {tariff_data['name']}"
        )
        await callback.answer('✅ Тариф добавлен!')
        await render_tariff_view(callback.message, tariff_id, state)

    except Exception as e:
        logger.error(f'Ошибка добавления тарифа: {e}', exc_info=True)
        await safe_edit_or_send(
            callback.message,
            f"❌ <b>Ошибка сохранения</b>\n\n<code>{e}</code>",
            reply_markup=back_and_home_kb('admin_tariffs'),
        )
        await callback.answer('❌ Ошибка', show_alert=True)


# ============================================================================
# РЕДАКТИРОВАНИЕ ТАРИФА
# ============================================================================


def get_edit_tariff_text(tariff: dict, current_param: int) -> str:
    params = get_tariff_params_list()
    total = len(params)
    param = params[current_param]
    current_value = tariff.get(param['key'])
    display_value = format_tariff_value(param, current_value)

    lines = [
        f"✏️ <b>Редактирование: {tariff['name']}</b> ({current_param + 1}/{total})\n",
        f"📌 Параметр: <b>{param['label']}</b>",
        f"📝 Текущее значение: <code>{display_value}</code>\n",
        f"Введите новое значение или используйте кнопки навигации:",
        f"_({param['hint']})_",
    ]
    if param.get('help'):
        lines.append(f"\n{param['help']}")
    return '\n'.join(lines)


@router.callback_query(F.data.startswith('admin_tariff_edit:'))
async def start_edit_tariff(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    tariff_id = int(callback.data.split(':')[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return

    await state.set_state(AdminStates.edit_tariff)
    await state.update_data(tariff_id=tariff_id, edit_param=0)
    total = get_total_tariff_params()
    await safe_edit_or_send(callback.message, get_edit_tariff_text(tariff, 0), reply_markup=edit_tariff_kb(0, total))
    await callback.answer()


@router.callback_query(F.data == 'admin_tariff_edit_prev')
async def edit_tariff_prev(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    data = await state.get_data()
    tariff = get_tariff_by_id(data.get('tariff_id'))
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return

    new_param = max(0, data.get('edit_param', 0) - 1)
    await state.update_data(edit_param=new_param)
    total = get_total_tariff_params()
    await safe_edit_or_send(callback.message, get_edit_tariff_text(tariff, new_param), reply_markup=edit_tariff_kb(new_param, total))
    await callback.answer()


@router.callback_query(F.data == 'admin_tariff_edit_next')
async def edit_tariff_next(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    data = await state.get_data()
    tariff = get_tariff_by_id(data.get('tariff_id'))
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return

    total = get_total_tariff_params()
    new_param = min(total - 1, data.get('edit_param', 0) + 1)
    await state.update_data(edit_param=new_param)
    await safe_edit_or_send(callback.message, get_edit_tariff_text(tariff, new_param), reply_markup=edit_tariff_kb(new_param, total))
    await callback.answer()


@router.message(AdminStates.edit_tariff)
async def edit_tariff_value(message: Message, state: FSMContext):
    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    current_param = data.get('edit_param', 0)
    param = get_tariff_param_by_index(current_param)

    from bot.utils.text import get_message_text_for_storage
    value = get_message_text_for_storage(message, 'plain')
    if not param['validate'](value):
        await safe_edit_or_send(message, f"❌ {param['error']}")
        return
    if 'convert' in param:
        value = param['convert'](value)

    success = update_tariff_field(tariff_id, param['key'], value)
    if success and param['key'] == 'duration_days':
        tariff = get_tariff_by_id(tariff_id)
        if tariff and _is_recurring(tariff):
            update_tariff_field(tariff_id, 'billing_period_days', value)

    if not success:
        await safe_edit_or_send(message, '❌ Ошибка сохранения')
        return

    try:
        await message.delete()
    except Exception:
        pass

    tariff = get_tariff_by_id(tariff_id)
    total = get_total_tariff_params()
    await safe_edit_or_send(
        message,
        f"✅ <b>{param['label']}</b> обновлено!\n\n" + get_edit_tariff_text(tariff, current_param),
        reply_markup=edit_tariff_kb(current_param, total),
        force_new=True,
    )


@router.callback_query(F.data == 'admin_tariff_edit_done')
async def edit_tariff_done(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    data = await state.get_data()
    await render_tariff_view(callback.message, data.get('tariff_id'), state)
    await callback.answer('✅ Готово')


@router.callback_query(F.data == 'admin_tariff_edit_cancel')
async def edit_tariff_cancel(callback: CallbackQuery, state: FSMContext):
    await edit_tariff_done(callback, state)


# ============================================================================
# ИЗМЕНЕНИЕ ГРУППЫ ТАРИФА
# ============================================================================


@router.callback_query(F.data.startswith('admin_tariff_change_group:'))
async def tariff_change_group_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    tariff_id = int(callback.data.split(':')[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return

    groups = get_all_groups()
    await state.update_data(tariff_id=tariff_id)
    await safe_edit_or_send(
        callback.message,
        f"📂 <b>Группа тарифа</b>\n\nТариф: <b>{tariff['name']}</b>\n\nВыберите новую группу:",
        reply_markup=group_select_kb(groups, 'tariff_change_group_select', f'admin_tariff_view:{tariff_id}'),
    )
    await callback.answer()


@router.callback_query(F.data.startswith('tariff_change_group_select:'))
async def tariff_change_group_selected(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer('⛔ Доступ запрещён', show_alert=True)
        return

    data = await state.get_data()
    tariff_id = data.get('tariff_id')
    group_id = int(callback.data.split(':')[1])
    if not tariff_id:
        await callback.answer('❌ Тариф не выбран', show_alert=True)
        return

    update_tariff(tariff_id, group_id=group_id)
    await callback.answer('✅ Группа обновлена')
    await render_tariff_view(callback.message, tariff_id, state)
