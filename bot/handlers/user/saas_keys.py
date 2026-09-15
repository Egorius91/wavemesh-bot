"""Private SaaS access views; no local panel is required to deliver material."""
from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.internal_api import InternalApiError, internal_api_client
from bot.utils.text import escape_html, safe_edit_or_send
from database.saas_access_projection import identity

router = Router()


def private_message(target, telegram_id):
    message = getattr(target, "message", None) or target
    if message.chat.type != "private" or message.chat.id != telegram_id:
        return None
    return message


async def dashboard(telegram_id):
    result = await internal_api_client.get_telegram_dashboard(telegram_id)
    user = result.get("user", {})
    if not isinstance(user, dict) or user.get("tenant_id") != internal_api_client.tenant_id:
        raise InternalApiError("Invalid access owner", code="INTERNAL_API_INVALID_RESPONSE")
    identity(user.get("user_id"))
    return result


def actions(access=None):
    rows = []
    if access and access.get("authority") == "managed":
        access_id = identity(access["access_id"])
        if access.get("status") == "ready" and access.get("enabled") is True:
            rows.append([InlineKeyboardButton(text="Получить конфигурацию", callback_data="saas_config:"+access_id)])
        key_id = access.get("legacy_key_id")
        if isinstance(key_id, str) and key_id.isdigit():
            rows.append([InlineKeyboardButton(text="Продлить", callback_data="key_renew:"+key_id)])
            if access.get("status") == "ready":
                rows.append([InlineKeyboardButton(text="Заменить ключ", callback_data="key_replace:"+key_id)])
    rows.extend([
        [InlineKeyboardButton(text="Автопродление", callback_data="saas_billing")],
        [InlineKeyboardButton(text="Мои ключи", callback_data="my_keys")],
        [InlineKeyboardButton(text="Главное меню", callback_data="start")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_list(target, telegram_id, *, page=0, force_new=False):
    message = private_message(target, telegram_id)
    if message is None:
        return
    try:
        result = await dashboard(telegram_id)
        accesses = [a for a in result.get("accesses", []) if isinstance(a, dict)]
        buttons = []
        for i, access in enumerate(accesses[page*20:(page+1)*20], page*20+1):
            access_id = access.get("access_id", "")
            # Legacy snapshot IDs are not material endpoints.
            if access.get("authority") != "managed":
                continue
            identity(access_id)
            if len(("saas_access:"+access_id).encode()) > 64:
                raise InternalApiError("Invalid access identity")
            buttons.append([InlineKeyboardButton(text=f"Доступ {i}", callback_data="saas_access:"+access_id)])
        if (page+1)*20 < len(accesses):
            buttons.append([InlineKeyboardButton(text="Далее", callback_data=f"saas_keys_page:{page+1}")])
        if page:
            buttons.append([InlineKeyboardButton(text="Назад", callback_data=f"saas_keys_page:{page-1}")])
        text = "Ваши доступы WaveMesh" if accesses else "У вас пока нет доступов WaveMesh."
        if any(a.get("authority") != "managed" for a in accesses):
            text += "\nЧасть старых ключей ожидает переноса. Для их проверки обратитесь в поддержку."
        buttons.extend(actions().inline_keyboard)
        await safe_edit_or_send(message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), force_new=force_new)
    except Exception:
        await safe_edit_or_send(message, "Не удалось получить доступы WaveMesh. Повторите позже.", force_new=force_new)


async def show_access(telegram_id, target, *, access_id=None, key_id=None, config=False):
    message = private_message(target, telegram_id)
    if message is None:
        return
    try:
        result = await dashboard(telegram_id)
        matches = [a for a in result.get("accesses", []) if isinstance(a, dict) and
                   (a.get("access_id") == access_id if access_id else a.get("legacy_key_id") == str(key_id))]
        if len(matches) != 1 or matches[0].get("authority") != "managed":
            raise InternalApiError("Access unavailable")
        access = matches[0]
        identity(access["access_id"])
        if config:
            from bot.handlers.user.payments.payment_return import load_verified_ready_payment_return, _render_verified_subscription
            verified = await load_verified_ready_payment_return(telegram_id=telegram_id, access_id=access["access_id"])
            await _render_verified_subscription(message, verified)
            return
        statuses = {"ready":"Готов", "materializing":"Настраивается", "pending":"Ожидает обработки",
                    "expired":"Срок истёк", "disabled":"Отключён", "suspended":"Приостановлен",
                    "revoked":"Отозван", "failed":"Требует проверки"}
        status = statuses.get(access.get("status"), "Ожидает подтверждения")
        text = f"<b>Доступ WaveMesh</b>\nСтатус: {status}\nСрок: {escape_html(str(access.get('expires_at') or '—'))}"
        await safe_edit_or_send(message, text, reply_markup=actions(access))
    except Exception:
        await safe_edit_or_send(message, "Доступ пока не удалось подтвердить. Повторите позже или обратитесь в поддержку.")


@router.callback_query(F.data.startswith("saas_access:"))
@router.callback_query(F.data.startswith("saas_config:"))
async def access_callback(callback):
    await callback.answer()
    await show_access(callback.from_user.id, callback, access_id=callback.data.split(":",1)[1],
                      config=callback.data.startswith("saas_config:"))


@router.callback_query(F.data.startswith("saas_keys_page:"))
async def page_callback(callback):
    await callback.answer()
    try:
        page = int(callback.data.split(":",1)[1])
    except ValueError:
        return
    if page >= 0:
        await show_list(callback, callback.from_user.id, page=page)
