"""Private confirmation UI for an immutable, recoverable replacement action."""
import hashlib
import json
import re

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.access_replacement import ReplacementWorker
from bot.services.internal_api import internal_api_client
from bot.services.private_chat import private_actor_id
from bot.utils.text import escape_html, safe_edit_or_send
from database.admin_provisioning import connection_scope


def worker():
    return ReplacementWorker(internal_api_client)


def callback_identity(callback, key_id):
    # Telegram update/callback IDs change on another click; the source message does not.
    return hashlib.sha256(json.dumps([connection_scope(internal_api_client), callback.from_user.id,
                                     callback.message.chat.id, callback.message.message_id, key_id]).encode()).hexdigest()


async def render(callback, row, runner):
    if private_actor_id(callback) != row["telegram_id"]:
        return
    buttons = InlineKeyboardBuilder()
    if row["phase"] == "PREPARED":
        text = "<b>Заменить ключ?</b>\nПосле завершения потребуется обновить настройки VPN. Срок и оплаченный тариф сохранятся."
        buttons.row(InlineKeyboardButton(text="Подтвердить замену", callback_data=f"replacement_confirm:{row['id']}"))
        buttons.row(InlineKeyboardButton(text="Отмена", callback_data=f"replacement_cancel:{row['id']}"))
    elif row["status"] == "DONE":
        text = "<b>Ключ заменён.</b>"
        # Re-fetch exact material; do not send whatever a local key contains after a later operation.
        try:
            _, material = await runner.ready_data(row, row["expected_version"]+1)
            text += "\nОбновите подписку в VPN-приложении:\n<code>"+escape_html(material["subscription_url"])+"</code>"
        except Exception:
            text += "\nАктуальная конфигурация доступна в разделе «Мои ключи»."
    elif row["phase"] == "CANCELLED":
        text = "Замена отменена или подтверждение устарело. Можно начать новое подтверждение."
    elif row["phase"] == "DONE":
        text = ("Эта операция завершена. Доступ был обновлён другой операцией." if row["status"] == "SUPERSEDED"
                else "Замену завершить не удалось. Проверьте состояние доступа или обратитесь в поддержку.")
    else:
        text = ("<b>Замена требует сверки.</b>\nОбратитесь в поддержку или проверьте результат позже."
                if row["status"] == "MANUAL_REVIEW" else
                "<b>Проверяем результат замены.</b>\nЗапрос сохранён. Повторная проверка не создаст новую замену или оплату.")
        buttons.row(InlineKeyboardButton(text="Проверить результат", callback_data=f"replacement_check:{row['id']}"))
    if row["phase"] in {"DONE", "CANCELLED"}:
        buttons.row(InlineKeyboardButton(text="Начать новую замену", callback_data=f"replacement_new:{row['id']}"))
    buttons.row(InlineKeyboardButton(text="Открыть доступ", callback_data=f"saas_access:{row['access_id']}"))
    await safe_edit_or_send(callback.message, text, reply_markup=buttons.as_markup())


async def begin_replacement(callback):
    actor = private_actor_id(callback)
    if actor is None:
        return
    await callback.answer()
    try:
        match = re.fullmatch(r"key_replace:([1-9][0-9]{0,17})", callback.data or "")
        if not match:
            return
        key_id = int(match[1])
        runner = worker()
        row = await runner.prepare(callback_identity(callback, key_id), key_id, actor)
        await render(callback, row, runner)
    except Exception:
        await safe_edit_or_send(callback.message, "Не удалось подготовить замену. Откройте доступ в «Мои ключи» или обратитесь в поддержку.")


async def replacement_action(callback):
    actor = private_actor_id(callback)
    if actor is None:
        return
    await callback.answer()
    try:
        match = re.fullmatch(r"replacement_(confirm|cancel|check|new):([a-f0-9]{32})", callback.data or "")
        if not match:
            return
        action, operation_id = match.groups()
        runner = worker()
        scope = connection_scope(internal_api_client)
        row = runner.journal.owned(operation_id, actor, scope)
        if action == "confirm":
            row = runner.journal.confirm(operation_id, actor, scope)
            row = await runner.reconcile(row["id"], explicit=True)
        elif action == "cancel":
            row = runner.journal.cancel(operation_id, actor, scope)
        elif action == "check":
            row = await runner.reconcile(operation_id, explicit=True)
        else:
            if row["phase"] not in {"DONE", "CANCELLED"}:
                raise ValueError("REPLACEMENT_UNRESOLVED")
            row = await runner.prepare("next:"+operation_id, row["key_id"], actor, previous_id=operation_id)
        await render(callback, row, runner)
    except Exception:
        await safe_edit_or_send(callback.message, "Результат пока не удалось подтвердить. Проверьте доступ позже или обратитесь в поддержку.")
