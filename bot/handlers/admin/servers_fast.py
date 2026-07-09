"""Быстрые экраны админки серверов.

Обычное открытие списка серверов и карточки сервера не должно ждать 3X-UI.
Статистика панели может быть недоступна, и из-за этого Telegram callback протухает.
Этот роутер подключается перед основным servers.py и перехватывает только
лёгкие экраны просмотра. Тяжёлые действия и refresh остаются в основном роутере.
"""
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from database.requests import (
    get_all_servers,
    get_server_by_id,
    get_groups_count,
    get_group_by_id,
    get_server_group_ids,
)
from bot.keyboards.admin import servers_list_kb, server_view_kb
from bot.states.admin_states import AdminStates
from bot.utils.admin import is_admin
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()


def _format_server_url(server: dict) -> str:
    return (
        f"{server.get('protocol', 'https')}://"
        f"{server.get('host', '')}:"
        f"{server.get('port', '')}"
        f"{server.get('web_base_path', '')}"
    )


async def get_servers_list_text_fast() -> str:
    """Формирует список серверов без запроса статистики 3X-UI."""
    servers = get_all_servers()
    if not servers:
        return (
            "🖥️ <b>Сервера</b>\n\n"
            "Серверов пока нет.\n"
            "Нажмите «➕ Добавить сервер» чтобы добавить первый!"
        )

    lines = ["🖥️ <b>Сервера</b>\n"]
    lines.append("<i>Статистика не загружается при открытии, чтобы админка отвечала быстро.</i>\n")

    for server in servers:
        status_emoji = "🟢" if server.get('is_active') else "🔴"
        status_text = "активен" if server.get('is_active') else "деактивирован"
        lines.append(
            f"{status_emoji} <b>{escape_html(server.get('name') or 'Сервер')}</b> "
            f"(<code>{escape_html(str(server.get('host') or ''))}:{escape_html(str(server.get('port') or ''))}</code>)"
        )
        lines.append(f"   Статус: {status_text}")
        lines.append("")

    return "\n".join(lines)


async def render_server_view_fast(message: Message, server_id: int, state: FSMContext):
    """Отрисовывает карточку сервера без запроса статистики 3X-UI."""
    server = get_server_by_id(server_id)
    if not server:
        return

    await state.set_state(AdminStates.server_view)
    await state.update_data(server_id=server_id)

    password = str(server.get('password') or '')
    password_masked = "•" * min(len(password), 8)
    status_emoji = "🟢" if server.get('is_active') else "🔴"
    status_text = "Активен" if server.get('is_active') else "Деактивирован"

    lines = [
        f"🖥️ <b>{escape_html(server.get('name') or 'Сервер')}</b>\n",
        f"🔗 URL панели: {escape_html(_format_server_url(server))}",
        f"👤 Логин: <code>{escape_html(str(server.get('login') or ''))}</code>",
        f"🔐 Пароль: <code>{password_masked}</code>\n",
        "🧩 <b>3x-ui API:</b>",
        f"   Версия: <code>{escape_html(server.get('panel_version') or 'не определена')}</code>",
        f"   Профиль: <code>{escape_html(server.get('panel_api_profile') or 'не определён')}</code>",
        f"   Проверка: <code>{escape_html(server.get('panel_checked_at') or 'ещё не выполнялась')}</code>\n",
        "📊 <b>Статистика:</b>",
        f"   {status_emoji} Статус: {status_text}",
        "   ℹ️ Не загружается при открытии экрана, чтобы админка не зависала.",
    ]

    groups_count = get_groups_count()
    if groups_count > 1:
        group_ids = get_server_group_ids(server_id)
        group_names = []
        for gid in group_ids:
            group = get_group_by_id(gid)
            if group:
                group_names.append(group['name'])
        groups_str = ", ".join(group_names) if group_names else "Основная"
        lines.append(f"\n📂 Группы: <code>{escape_html(groups_str)}</code>")

    await safe_edit_or_send(
        message,
        "\n".join(lines),
        reply_markup=server_view_kb(server_id, server.get('is_active'), groups_count > 1),
    )


@router.callback_query(F.data == "admin_servers")
async def show_servers_list_fast(callback: CallbackQuery, state: FSMContext):
    """Быстро показывает список серверов без статистики панели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()
    await state.set_state(AdminStates.servers_list)
    await state.update_data(server_data={})

    text = await get_servers_list_text_fast()
    servers = get_all_servers()
    await safe_edit_or_send(callback.message, text, reply_markup=servers_list_kb(servers))


@router.callback_query(F.data.startswith("admin_server_view:"))
async def show_server_view_fast(callback: CallbackQuery, state: FSMContext):
    """Быстро показывает карточку сервера без статистики панели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    server_id = int(callback.data.split(":")[1])
    server = get_server_by_id(server_id)
    if not server:
        await callback.answer("❌ Сервер не найден", show_alert=True)
        return

    await callback.answer()
    await render_server_view_fast(callback.message, server_id, state)
