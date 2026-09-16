"""Private shared checkout UX over the durable SaaS adapter."""
import hashlib
import json
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.checkout_contract import TERMINAL, intent_terms
from bot.services.checkout_coordinator import CheckoutCoordinator
from bot.services.internal_api import internal_api_client
from bot.services.private_chat import private_actor_id
from bot.utils.text import escape_html, safe_edit_or_send
from database.admin_provisioning import JournalConflict
from database.checkout_ui import CheckoutUIJournal

UNKNOWN = "Статус оплаты пока не подтверждён. Проверьте исходную оплату позже или обратитесь в поддержку."


def coordinator():
    return CheckoutCoordinator(internal_api_client)


def ui_journal():
    return CheckoutUIJournal()


def source_key(callback):
    # Callback.id changes on every tap; the source message/action does not.
    return "tg-" + hashlib.sha256(json.dumps([callback.from_user.id, callback.message.chat.id,
                                             callback.message.message_id, callback.data]).encode()).hexdigest()


def buttons():
    return InlineKeyboardBuilder()


def add(builder, text, data):
    builder.row(InlineKeyboardButton(text=text, callback_data=data))


def navigation(builder):
    add(builder, "Мои ключи", "my_keys")
    add(builder, "Главная и поддержка", "home")


async def send(event, text, builder):
    target = event.message if isinstance(event, CallbackQuery) else event
    await safe_edit_or_send(target, text, reply_markup=builder.as_markup(), force_new=not isinstance(event, CallbackQuery))


async def failure(event):
    builder = buttons()
    add(builder, "Проверить исходную оплату", "wmco_current")
    navigation(builder)
    await send(event, UNKNOWN, builder)


async def render(event, result, runner, *, key_id=None, expose_url=False):
    actor = private_actor_id(event)
    if actor is None:
        return
    owner, scope, _ = await runner.context(actor)
    row, current = result.get("operation"), result.get("current")
    # Recheck private identity immediately before delivery, not only before IO.
    if row:
        row = runner.journal.owned(row["id"], actor, scope, owner)
    builder = buttons()
    if row and row["phase"] == "PREPARED" and not result.get("unresolved"):
        payload = json.loads(row["payload"])
        terms = intent_terms(payload)
        recurring = payload["billing_mode"] == "RECURRING"
        target = "Продление выбранного доступа" if payload.get("access_id") else "Новый доступ"
        heading = "Подтвердите подписку" if recurring else "Подтвердите разовую оплату"
        price = (f"{terms['amountRub']} ₽ каждые {terms['durationDays']} дней через ЮKassa." if recurring
                 else f"{terms['amountRub']} ₽ за {terms['durationDays']} дней без автопродления.")
        text = (f"<b>{heading}</b>\n{escape_html(row['name'])}\n{target}.\n{price}\n"
                f"Устройств: {terms['deviceLimit'] or 'без ограничения'}. "
                f"Трафик: {str(terms['trafficLimitGb'])+' ГБ' if terms['trafficLimitGb'] else 'без ограничения'}.\n\n")
        if recurring:
            text += ("Способ оплаты будет сохранён для автопродления. Его можно отключить в кабинете; оплаченный период сохранится.\n"
                     "Нажимая «Согласен и оплатить», вы соглашаетесь на сохранение способа оплаты и автопродление на этих условиях.")
        else:
            text += "Платёжный сервис выберет WaveMesh. После окончания срока новых списаний не будет."
        add(builder, "Согласен и оплатить" if recurring else "Подтвердить и оплатить", "wmco_confirm:"+row["id"])
        add(builder, "Отмена", "wmco_cancel:"+row["id"])
    else:
        ref = ui_journal().create(actor, scope, owner, "STATUS", {
            "operation_id": row["id"] if row else None, "order_id": current["order_id"] if current else None, "key_id": key_id})
        text = UNKNOWN if result.get("unresolved") else "<b>Ваша оплата подписки</b>"
        if current:
            terms = current["terms"]["recurring_consent"]
            text += f"\n{escape_html(current['terms']['name'])}: {terms['amountRub']} ₽ за {terms['durationDays']} дней."
            text += "\nПродление доступа." if current["purchase_kind"] == "RENEWAL" else "\nНовый доступ."
            status = current["payment_status"]
            if status == "PAID":
                text += "\nОплата подтверждена."
                text += "\nКонфигурация готова — откройте «Мои ключи» для подключения." if current["configuration_ready"] else "\nДоступ подготавливается. Его состояние доступно в «Мои ключи»."
                text += ("\nРазовая оплата без автопродления." if current["billing_mode"] == "ONE_TIME" else
                         "\nАвтопродление включено." if current["recurring"] == "ACTIVE" else "\nСостояние автопродления проверяйте в кабинете.")
            elif status == "PREPARING":
                text += "\nЗаказ ещё не отправлен на оплату. Для отмены откройте эту оплату на сайте в связанном аккаунте или обратитесь в поддержку."
            elif status == "CANCELLED":
                text += "\nОплата отменена."
            elif status == "REFUNDED":
                text += "\nВозврат подтверждён. Состояние доступа проверяйте в кабинете."
            else:
                text += "\nОжидаем подтверждения исходной оплаты."
            if current["checkout_url"]:
                if expose_url:
                    builder.row(InlineKeyboardButton(text="Перейти к исходной оплате", url=current["checkout_url"]))
                else:
                    add(builder, "Получить ссылку на оплату", "wmco_pay:"+ref)
            if status in TERMINAL and not result.get("unresolved") and (not row or row["phase"] in {"TERMINAL", "CANCELLED"}):
                add(builder, "Начать новую покупку", "wmco_next:"+ref)
        elif row and row["phase"] == "TERMINAL" and row["payment_status"] == "NOT_ADMITTED" and not result.get("unresolved"):
            text = "Покупка не создана. Заново выберите тариф и подтвердите актуальные условия."
            if json.loads(row["payload"]).get("access_id"):
                add(builder, "Выбрать доступ для продления", "my_keys")
            else:
                add(builder, "Выбрать тариф", "buy_key")
        elif row and row["phase"] == "CANCELLED":
            text = "Подтверждение отменено. Запрос на оплату не отправлялся."
            add(builder, "Выбрать тариф", "buy_key")
        elif not row:
            text = "Текущая оплата подписки не найдена."
            add(builder, "Выбрать тариф", "buy_key")
        if (row and row["phase"] in {"DISPATCHED", "REJECTED"} and row["order_id"] is None
                and result.get("original") is None and result.get("unresolved")):
            text += ("\n\nЕсли заказ по этой попытке не появился, можно завершить попытку. "
                     "Сервис ещё раз проверит исходный запрос; после подтверждённого отказа тариф потребуется выбрать заново.")
            add(builder, "Завершить попытку", "wmco_reject:"+row["id"])
        add(builder, "Проверить оплату", "wmco_check:"+ref)
        if row and row["phase"] == "PREPARED":
            add(builder, "Отменить подтверждение", "wmco_cancel:"+row["id"])
    navigation(builder)
    await send(event, text, builder)


async def renewal_access(callback, key_id):
    if key_id is None:
        return None
    from . import saas
    context = await saas._load_checkout_context(callback, key_id)
    if context is None:
        raise JournalConflict("CHECKOUT_TARGET_CHANGED")
    return context[1]["access"]["access_id"]


async def catalog(event, runner, *, key_id=None, previous=None):
    actor = private_actor_id(event)
    owner, scope, _ = await runner.context(actor)
    result = await runner.recover(actor)
    current, row = result["current"], result["operation"]
    if row or (current and (current["order_id"] != previous or current["payment_status"] not in TERMINAL)):
        await render(event, result, runner, key_id=key_id)
        return
    if previous and not current:
        raise JournalConflict("CHECKOUT_PREDECESSOR_MISSING")
    tariffs = await runner.client.list_tariffs()
    builder = buttons()
    from .saas import _tariff_button_text
    for tariff in tariffs:
        if not isinstance(tariff, dict) or tariff.get("billing_mode") not in {"RECURRING", "ONE_TIME"}:
            continue
        if not isinstance(tariff.get("tariff_id"), str):
            continue
        ref = ui_journal().create(actor, scope, owner, "CHOICE", {
            "tariff_id": tariff["tariff_id"], "key_id": key_id, "previous": previous})
        add(builder, _tariff_button_text(tariff), "wmco_select:"+ref)
    navigation(builder)
    await send(event, "<b>Выберите тариф</b>\nПосле выбора подтвердите сумму и срок. Для подписки отдельно подтвердите условия автопродления.", builder)


async def entry(event):
    actor = private_actor_id(event)
    if actor is None:
        return
    if isinstance(event, CallbackQuery):
        await event.answer()
    try:
        key_id = int(event.data.split(":", 1)[1]) if isinstance(event, CallbackQuery) and event.data.startswith("key_renew:") else None
        runner = coordinator()
        # Readback is independent of the current catalog and creation gates.
        await catalog(event, runner, key_id=key_id)
    except Exception:
        await failure(event)


async def select(event, *, tariff_id, key_id=None, previous=None, callback_key=None, legacy_provider=None):
    actor = private_actor_id(event)
    runner = coordinator()
    owner, scope, _ = await runner.context(actor)
    stable = callback_key or source_key(event)
    prior = runner.journal.for_callback(stable, actor, scope, owner)
    if prior:
        await render(event, await runner.recover(actor, prior["id"]), runner, key_id=key_id)
        return
    result = await runner.recover(actor)
    current = result["current"]
    if result["operation"] or current and (current["order_id"] != previous or current["payment_status"] not in TERMINAL):
        if result["operation"]:
            runner.journal.attach(stable, result["operation"]["id"], actor, scope, owner)
        await render(event, result, runner, key_id=key_id)
        return
    if previous and not current:
        raise JournalConflict("CHECKOUT_PREDECESSOR_MISSING")
    tariffs = await runner.client.list_tariffs()
    matches = [t for t in tariffs if isinstance(t, dict) and t.get("tariff_id") == tariff_id]
    if len(matches) != 1:
        raise JournalConflict("CHECKOUT_TARIFF_UNAVAILABLE")
    selected = matches[0]
    if selected.get("billing_mode") == "RECURRING" and legacy_provider not in {None, "YOOKASSA"}:
        await send(event, "Для подписки сейчас доступна ЮKassa. Заново выберите тариф и подтвердите условия.", buttons().row(InlineKeyboardButton(text="Выбрать тариф", callback_data="buy_key")))
        return
    access_id = await renewal_access(event, key_id)
    prepared = await runner.prepare(actor, stable, tariff_id, access_id=access_id, previous=previous)
    row = prepared["operation"]
    await render(event, await runner.recover(actor, row["id"]) if row else prepared, runner, key_id=key_id)


async def legacy_selection(event):
    if private_actor_id(event) is None:
        return
    await event.answer()
    try:
        data = event.data.split(":")
        key_id, provider = None, None
        if data[0] == "saas_new_checkout" and len(data) == 2:
            tariff_id = data[1]
        elif data[0] == "saas_checkout" and len(data) == 3:
            key_id, tariff_id = int(data[1]), data[2]
        elif data[0] == "saas_np" and len(data) == 3:
            provider, tariff_id = {"yk": "YOOKASSA", "pg": "PLATEGA"}[data[1]], data[2]
        elif data[0] == "saas_rp" and len(data) == 4:
            key_id, provider, tariff_id = int(data[1]), {"yk": "YOOKASSA", "pg": "PLATEGA"}[data[2]], data[3]
        else:
            raise JournalConflict("INVALID_CHECKOUT_CALLBACK")
        await select(event, tariff_id=tariff_id, key_id=key_id, legacy_provider=provider)
    except Exception:
        await failure(event)


async def action(event):
    actor = private_actor_id(event)
    if actor is None:
        return
    await event.answer()
    try:
        runner = coordinator()
        if event.data == "wmco_current":
            await render(event, await runner.recover(actor), runner)
            return
        match = re.fullmatch(r"wmco_(select|confirm|cancel|reject|check|pay|next):([a-f0-9]{32})", event.data or "")
        if not match:
            raise JournalConflict("INVALID_CHECKOUT_CALLBACK")
        kind, ref = match.groups()
        if kind in {"confirm", "cancel", "reject"}:
            if kind == "cancel":
                await runner.cancel(actor, ref)
                result = await runner.recover(actor, ref)
            elif kind == "reject":
                result = await runner.reject_unadmitted(actor, ref)
            else:
                result = await runner.confirm(actor, ref)
            await render(event, result, runner)
            return
        owner, scope, _ = await runner.context(actor)
        payload = ui_journal().owned(ref, actor, scope, owner, "CHOICE" if kind == "select" else "STATUS")
        if kind == "select":
            await select(event, tariff_id=payload["tariff_id"], key_id=payload["key_id"], previous=payload["previous"], callback_key="choice-"+ref)
            return
        result = await runner.recover(actor, payload["operation_id"])
        current = result["current"]
        if kind == "check":
            await render(event, result, runner, key_id=payload["key_id"])
            return
        if not current or current["order_id"] != payload["order_id"]:
            await render(event, result, runner, key_id=payload["key_id"])
            return
        if kind == "pay":
            await render(event, result, runner, key_id=payload["key_id"], expose_url=True)
        elif current["payment_status"] in TERMINAL and not result["unresolved"]:
            await catalog(event, runner, key_id=payload["key_id"], previous=current["order_id"])
        else:
            await render(event, result, runner, key_id=payload["key_id"])
    except Exception:
        await failure(event)


def build_router():
    result = Router()
    result.message.register(entry, Command("buy"))
    result.callback_query.register(entry, (F.data == "buy_key") | F.data.startswith("key_renew:"))
    result.callback_query.register(action, F.data.startswith("wmco_"))
    result.callback_query.register(legacy_selection, F.data.startswith("saas_new_checkout:") | F.data.startswith("saas_checkout:") |
                                   F.data.startswith("saas_np:") | F.data.startswith("saas_rp:"))
    return result


router = build_router()
