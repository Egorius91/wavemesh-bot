"""
Обработчики раздела «Настройки бота».

Файл содержит только автономные системные функции бота: настройки,
обновление из GitHub, работу с логами и остановку процесса.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, FSInputFile

from config import GITHUB_REPO_URL
from bot.keyboards.admin import (
    admin_logs_menu_kb,
    back_and_home_kb,
    bot_mode_toggle_confirm_kb,
    bot_settings_kb,
    force_overwrite_confirm_kb,
    stop_bot_confirm_kb,
    update_confirm_kb,
)
from bot.utils.admin import is_admin
from bot.utils.git_utils import (
    check_for_updates,
    force_pull_updates,
    get_current_branch,
    get_current_commit,
    get_last_commit_info,
    get_previous_commits_info,
    get_remote_url,
    install_requirements,
    pull_to_commit,
    pull_updates,
    restart_bot,
    set_remote_url,
)
from bot.utils.text import safe_edit_or_send
from bot.utils.update_block import (
    get_blocked_message,
    is_update_blocked,
    set_update_blocked,
    try_unblock,
)

logger = logging.getLogger(__name__)
router = Router()


# ============================================================================
# ГЛАВНОЕ МЕНЮ НАСТРОЕК
# ============================================================================

@router.callback_query(F.data == "admin_bot_settings")
async def show_bot_settings(callback: CallbackQuery, state: FSMContext):
    """Показывает меню настроек бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.services.vpn_api import get_bot_mode

    mode = get_bot_mode()
    if mode == "subscription":
        mode_label = "📡 Подписка"
        mode_desc = (
            "Бот выдаёт пользователю одну <b>subscription-ссылку</b> — "
            "клиент сам подтягивает все протоколы сервера."
        )
    else:
        mode_label = "🔑 Ключи"
        mode_desc = (
            "Бот создаёт один VLESS/VMess-клиент в одном inbound "
            "и выдаёт ссылку + JSON-конфиг."
        )

    text = (
        "⚙️ <b>Настройки бота</b>\n\n"
        f"<b>Режим работы:</b> {mode_label}\n"
        f"<i>{mode_desc}</i>\n\n"
        "Выберите действие:"
    )
    await safe_edit_or_send(callback.message, text, reply_markup=bot_settings_kb(mode))
    await callback.answer()


@router.callback_query(F.data == "admin_toggle_bot_mode")
async def admin_toggle_bot_mode(callback: CallbackQuery, state: FSMContext):
    """Показывает экран подтверждения переключения режима работы бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from bot.services.vpn_api import get_bot_mode

    current = get_bot_mode()
    target = "key" if current == "subscription" else "subscription"

    if target == "subscription":
        warning = (
            "⚠️ <b>Переключение в режим Подписка</b>\n\n"
            "При ближайших синхронизациях бот создаст клиентов во всех inbound "
            "каждого сервера для существующих ключей. Новые ключи будут выдаваться "
            "как <b>subscription URL</b>.\n\n"
            "Продолжить?"
        )
    else:
        warning = (
            "⚠️ <b>Переключение в режим Ключи</b>\n\n"
            "При ближайших синхронизациях бот оставит на каждом сервере по одному "
            "клиенту на каждый ключ. Новые ключи будут выдаваться как одна ссылка.\n\n"
            "<b>Subscription URL у пользователей перестанут работать.</b>\n\n"
            "Продолжить?"
        )

    await safe_edit_or_send(
        callback.message,
        warning,
        reply_markup=bot_mode_toggle_confirm_kb(target),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_set_bot_mode:"))
async def admin_set_bot_mode(callback: CallbackQuery, state: FSMContext):
    """Сохраняет новый режим работы бота в settings."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    target = callback.data.split(":", 1)[1]
    if target not in ("subscription", "key"):
        await callback.answer("⛔ Недопустимое значение", show_alert=True)
        return

    from database.db_settings import set_setting

    set_setting("bot_mode", target)
    logger.info("Bot mode switched to %s by admin %s", target, callback.from_user.id)
    label = "📡 Подписка" if target == "subscription" else "🔑 Ключи"
    await callback.answer(f"✅ Режим установлен: {label}", show_alert=True)
    await show_bot_settings(callback, state)


# ============================================================================
# ОБНОВЛЕНИЕ БОТА
# ============================================================================

def _ensure_remote_url() -> None:
    """Синхронизирует remote origin с GITHUB_REPO_URL, если он задан."""
    if not GITHUB_REPO_URL:
        return
    current_remote = get_remote_url()
    if current_remote != GITHUB_REPO_URL:
        set_remote_url(GITHUB_REPO_URL)


@router.message(Command("update"))
async def admin_update_cmd(message: Message, state: FSMContext):
    """Скрытая команда экстренного обновления для администраторов."""
    if not is_admin(message.from_user.id):
        return

    _ensure_remote_url()
    await safe_edit_or_send(
        message,
        "🔄 <b>Экстренное обновление...</b>\n\nЗагружаю изменения с GitHub...",
    )

    success, log_message = pull_updates()
    if not success:
        await safe_edit_or_send(message, f"❌ <b>Ошибка обновления</b>\n\n{log_message}")
        return

    logger.info("Bot manually updated by admin %s via /update", message.from_user.id)
    await safe_edit_or_send(
        message,
        f"✅ <b>Обновление завершено!</b>\n\n{log_message}\n\n"
        "🔄 Перезапуск бота через 2 секунды...",
        force_new=True,
    )
    await state.clear()
    await asyncio.sleep(2)

    success, req_message = install_requirements()
    if not success:
        logger.error("Ошибка установки зависимостей: %s", req_message)
        await safe_edit_or_send(
            message,
            f"⚠️ <b>Ошибка установки зависимостей</b>\n\n{req_message}\n\n"
            "Бот не будет перезапущен. Проверьте requirements.txt и попробуйте снова.",
            force_new=True,
        )
        return

    restart_bot()


@router.callback_query(F.data == "admin_update_bot")
async def show_update_confirm(callback: CallbackQuery, state: FSMContext):
    """Показывает подтверждение обновления."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    if not GITHUB_REPO_URL:
        await safe_edit_or_send(
            callback.message,
            "❌ <b>GitHub не настроен</b>\n\n"
            "Укажите URL репозитория в файле <code>config.py</code>:\n"
            '<code>GITHUB_REPO_URL = "https://github.com/user/repo.git"</code>',
            reply_markup=back_and_home_kb("admin_bot_settings"),
        )
        await callback.answer()
        return

    _ensure_remote_url()
    try_unblock()

    if is_update_blocked():
        await safe_edit_or_send(
            callback.message,
            get_blocked_message(),
            reply_markup=back_and_home_kb("admin_bot_settings"),
        )
        await callback.answer()
        return

    await safe_edit_or_send(
        callback.message,
        "🔍 <b>Проверка обновлений...</b>\n\nПодключаюсь к GitHub...",
    )

    success, commits_behind, log_text, has_blocking, blocking_commit, is_beta_only = check_for_updates()
    if not success:
        await safe_edit_or_send(
            callback.message,
            f"❌ <b>Ошибка проверки</b>\n\n{log_text}",
            reply_markup=back_and_home_kb("admin_bot_settings"),
        )
        await callback.answer()
        return

    commit_hash = get_current_commit() or "неизвестно"
    branch = get_current_branch() or "main"
    target_rev = f"origin/{branch}" if commits_behind > 0 else "HEAD"
    last_commit = get_last_commit_info(target_rev)
    previous_commits = get_previous_commits_info(5, target_rev)

    commits_text = f"🔹 <b>Последний коммит:</b>\n<code>{last_commit}</code>\n"
    if previous_commits != "Нет предыдущих коммитов":
        commits_text += f"\n🔸 <b>Предыдущие 5 коммитов:</b>\n<code>{previous_commits}</code>"

    await state.update_data(has_blocking=has_blocking, blocking_commit=blocking_commit)

    if commits_behind == 0:
        text = (
            "✅ <b>Обновление не требуется, у вас последняя версия</b>\n\n"
            f"Текущая версия: <code>{commit_hash}</code>\n\n{commits_text}"
        )
        markup = update_confirm_kb(has_updates=False)
    elif has_blocking and blocking_commit:
        blocking_msg = blocking_commit["message"].lstrip("!")
        blocking_hash = blocking_commit["hash"][:8]
        text = (
            "⚠️ <b>Блокирующее обновление!</b>\n\n"
            f"📦 <b>Доступно обновлений:</b> {commits_behind}\n"
            f"Текущая версия: <code>{commit_hash}</code>\n\n"
            f"🚫 Найден блокирующий коммит <code>{blocking_hash}</code>:\n"
            f"<code>{blocking_msg}</code>\n\n"
            f"{commits_text}"
        )
        markup = update_confirm_kb(has_updates=True, has_blocking=True)
    elif is_beta_only:
        text = (
            "🧪 <b>Доступна бета-версия!</b>\n\n"
            f"📦 <b>Доступно бета-коммитов:</b> {commits_behind}\n"
            f"Текущая версия: <code>{commit_hash}</code>\n\n"
            f"{commits_text}\n\n"
            "⚠️ Это тестовая версия. Устанавливайте на свой страх и риск."
        )
        markup = update_confirm_kb(has_updates=True, is_beta_only=True)
    else:
        text = (
            f"📦 <b>Доступно обновлений:</b> {commits_behind}\n\n"
            f"Текущая версия: <code>{commit_hash}</code>\n\n"
            f"{commits_text}\n\n"
            "⚠️ После обновления бот автоматически перезапустится."
        )
        markup = update_confirm_kb(has_updates=True)

    await safe_edit_or_send(callback.message, text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data == "admin_update_bot_confirm")
async def update_bot_confirmed(callback: CallbackQuery, state: FSMContext):
    """Выполняет обновление и перезапуск бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    _ensure_remote_url()
    data = await state.get_data()
    has_blocking = data.get("has_blocking", False)
    blocking_commit = data.get("blocking_commit")

    if has_blocking and blocking_commit:
        await safe_edit_or_send(
            callback.message,
            "🔄 <b>Блокирующее обновление...</b>\n\n"
            f"Обновляю до коммита <code>{blocking_commit['hash'][:8]}</code>...",
        )
        success, message = pull_to_commit(blocking_commit["hash"])
    else:
        await safe_edit_or_send(
            callback.message,
            "🔄 <b>Обновление...</b>\n\nЗагружаю изменения с GitHub...",
        )
        success, message = pull_updates()

    if not success:
        await safe_edit_or_send(
            callback.message,
            f"❌ <b>Ошибка обновления</b>\n\n{message}",
            reply_markup=back_and_home_kb("admin_bot_settings"),
        )
        await callback.answer()
        return

    logger.info("Bot updated by admin %s", callback.from_user.id)
    if has_blocking:
        set_update_blocked()

    await safe_edit_or_send(
        callback.message,
        f"✅ <b>Обновление завершено!</b>\n\n{message}\n\n"
        "🔄 Перезапуск бота через 2 секунды...",
    )
    await callback.answer("Бот перезапускается...", show_alert=True)
    await state.clear()
    await asyncio.sleep(2)

    success, req_message = install_requirements()
    if not success:
        logger.error("Ошибка установки зависимостей: %s", req_message)
        await safe_edit_or_send(
            callback.message,
            f"⚠️ <b>Ошибка установки зависимостей</b>\n\n{req_message}\n\n"
            "Бот не будет перезапущен. Проверьте requirements.txt и попробуйте снова.",
        )
        return

    restart_bot()


@router.callback_query(F.data == "admin_force_overwrite")
async def show_force_overwrite(callback: CallbackQuery, state: FSMContext):
    """Показывает предупреждение перед принудительной перезаписью."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    if not GITHUB_REPO_URL:
        await safe_edit_or_send(
            callback.message,
            "❌ <b>GitHub не настроен</b>\n\n"
            "Укажите URL репозитория в файле <code>config.py</code>.",
            reply_markup=back_and_home_kb("admin_bot_settings"),
        )
        await callback.answer()
        return

    await safe_edit_or_send(
        callback.message,
        "⚠️ <b>ПРИНУДИТЕЛЬНАЯ ПЕРЕЗАПИСЬ</b>\n\n"
        f"Все файлы бота, кроме конфигурации и баз данных, будут перезаписаны из:\n"
        f"<code>{GITHUB_REPO_URL}</code>\n\n"
        "Локальные изменения в коде будут потеряны. Продолжить?",
        reply_markup=force_overwrite_confirm_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_force_overwrite_confirm")
async def force_overwrite_confirmed(callback: CallbackQuery, state: FSMContext):
    """Выполняет принудительную перезапись и перезапуск бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    _ensure_remote_url()
    await safe_edit_or_send(
        callback.message,
        "🔄 <b>Принудительная перезапись...</b>\n\nСвязываюсь с репозиторием...",
    )

    success, message = force_pull_updates()
    if not success:
        await safe_edit_or_send(
            callback.message,
            f"❌ <b>Ошибка перезаписи</b>\n\n{message}",
            reply_markup=back_and_home_kb("admin_bot_settings"),
        )
        await callback.answer()
        return

    logger.info("Bot force-overwritten by admin %s", callback.from_user.id)
    await safe_edit_or_send(
        callback.message,
        f"✅ <b>Успешно!</b>\n\n{message}\n\n🔄 Перезапуск бота через 2 секунды...",
    )
    await callback.answer("Бот перезапускается...", show_alert=True)
    await state.clear()
    await asyncio.sleep(2)

    success, req_message = install_requirements()
    if not success:
        logger.error("Ошибка установки зависимостей: %s", req_message)
        await safe_edit_or_send(
            callback.message,
            f"⚠️ <b>Ошибка установки зависимостей</b>\n\n{req_message}\n\n"
            "Бот не будет перезапущен. Проверьте requirements.txt и попробуйте снова.",
        )
        return

    restart_bot()


# ============================================================================
# ЛОГИ
# ============================================================================

@router.callback_query(F.data == "admin_logs_menu")
async def admin_logs_menu(callback: CallbackQuery, state: FSMContext):
    """Показывает меню логов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await safe_edit_or_send(
        callback.message,
        "📥 <b>Логи</b>\n\nВыберите действие:",
        reply_markup=admin_logs_menu_kb(),
    )
    await callback.answer()


def _log_file_path(kind: str) -> Path:
    if kind == "errors":
        return Path("logs") / "errors.log"
    return Path("logs") / "bot.log"


async def _send_log_file(callback: CallbackQuery, kind: str) -> None:
    path = _log_file_path(kind)
    if not path.exists():
        await callback.answer("Файл логов не найден", show_alert=True)
        return

    await callback.message.answer_document(FSInputFile(path), caption=f"📄 Лог: {path.name}")
    await callback.answer()


@router.callback_query(F.data == "admin_download_log_full")
async def admin_download_log_full(callback: CallbackQuery, state: FSMContext):
    """Отправляет полный лог."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await _send_log_file(callback, "full")


@router.callback_query(F.data == "admin_download_log_errors")
async def admin_download_log_errors(callback: CallbackQuery, state: FSMContext):
    """Отправляет лог ошибок."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await _send_log_file(callback, "errors")


@router.callback_query(F.data == "admin_clear_logs_confirm")
async def admin_clear_logs_confirm(callback: CallbackQuery, state: FSMContext):
    """Очищает локальные файлы логов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    cleared = []
    for path in (Path("logs") / "bot.log", Path("logs") / "errors.log"):
        if path.exists():
            path.write_text("", encoding="utf-8")
            cleared.append(path.name)

    text = "✅ Логи очищены." if cleared else "ℹ️ Файлы логов не найдены."
    await safe_edit_or_send(callback.message, text, reply_markup=back_and_home_kb("admin_logs_menu"))
    await callback.answer()


# ============================================================================
# ОСТАНОВКА БОТА
# ============================================================================

@router.callback_query(F.data == "admin_stop_bot")
async def admin_stop_bot(callback: CallbackQuery, state: FSMContext):
    """Показывает подтверждение остановки бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await safe_edit_or_send(
        callback.message,
        "🛑 <b>Остановка бота</b>\n\nВы действительно хотите остановить процесс?",
        reply_markup=stop_bot_confirm_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_stop_bot_confirm")
async def admin_stop_bot_confirm(callback: CallbackQuery, state: FSMContext):
    """Останавливает процесс бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await safe_edit_or_send(callback.message, "🛑 Бот останавливается...")
    await callback.answer("Бот останавливается", show_alert=True)
    await state.clear()
    logger.warning("Bot stopped by admin %s", callback.from_user.id)
    await asyncio.sleep(1)
    os._exit(0)


# ============================================================================
# РЕДАКТИРОВАНИЕ ТЕКСТОВ
# ============================================================================

@router.callback_query(F.data == "admin_edit_texts")
async def edit_texts_menu(callback: CallbackQuery, state: FSMContext):
    """Перенаправляет к штатному редактору сообщений, если он подключён."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await safe_edit_or_send(
        callback.message,
        "✏️ <b>Редактирование текстов</b>\n\n"
        "Раздел будет вынесен в отдельный штатный редактор сообщений.",
        reply_markup=back_and_home_kb("admin_bot_settings"),
    )
    await callback.answer()
