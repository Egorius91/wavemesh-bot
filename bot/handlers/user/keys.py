import logging
import uuid
import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramForbiddenError
from config import ADMIN_IDS
from database.requests import get_or_create_user, is_user_banned, get_all_servers, get_setting, is_referral_enabled, get_user_by_referral_code, set_user_referrer
from bot.keyboards.user import main_menu_kb
from bot.states.user_states import RenameKey, ReplaceKey
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

@router.message(Command('mykeys', 'my_keys'))
async def cmd_mykeys(message: Message, state: FSMContext):
    """Обработчик команды /mykeys - вызывает логику кнопки 'Мои ключи'."""
    if is_user_banned(message.from_user.id):
        await safe_edit_or_send(message, '⛔ <b>Доступ заблокирован</b>\n\nВаш аккаунт заблокирован. Обратитесь в поддержку.', force_new=True)
        return
    await state.clear()
    await show_my_keys(message.from_user.id, message, is_callback=False)

async def _build_my_keys_render_data(telegram_id: int):
    """Готовит текст списка и динамические кнопки ключей."""
    from database.requests import get_user_keys_for_display, get_setting, is_traffic_exhausted
    from bot.services.vpn_api import get_client, format_traffic
    from bot.utils.my_keys_page import (
        DEFAULT_MY_KEYS_ITEM_TEMPLATE,
        MY_KEYS_ITEM_TEMPLATE_SETTING,
        build_my_keys_item_text,
        build_my_keys_list_text,
    )

    keys = get_user_keys_for_display(telegram_id)
    item_template = get_setting(
        MY_KEYS_ITEM_TEMPLATE_SETTING,
        DEFAULT_MY_KEYS_ITEM_TEMPLATE,
    )
    if item_template is None:
        item_template = DEFAULT_MY_KEYS_ITEM_TEMPLATE
    items = []
    key_buttons = []

    for key in keys:
        traffic_exhausted = is_traffic_exhausted(key)
        if key['is_active'] and not traffic_exhausted:
            status_emoji = '🟢'
        else:
            status_emoji = '🔴'

        traffic_used = key.get('traffic_used', 0) or 0
        traffic_limit = key.get('traffic_limit', 0) or 0
        used_str = format_traffic(traffic_used)
        limit_str = format_traffic(traffic_limit) if traffic_limit > 0 else '∞'
        traffic_text = f'{used_str} / {limit_str}'

        protocol = 'VLESS'
        inbound_name = 'VPN'
        if key.get('sub_id'):
            protocol = 'SUBSCRIPTION'
            inbound_name = 'Все протоколы'
        elif key.get('server_id') and key.get('panel_email'):
            try:
                client = await get_client(key['server_id'])
                stats = await client.get_client_stats(key['panel_email'])
                if stats:
                    protocol = stats['protocol'].upper()
                    inbound_name = stats.get('remark', 'VPN') or 'VPN'
            except Exception as e:
                logger.warning(f"Не удалось получить протокол для ключа {key['id']}: {e}")

        items.append(
            build_my_keys_item_text(
                key,
                template=item_template,
                status=status_emoji,
                traffic_text=traffic_text,
                inbound_name=inbound_name,
                protocol=protocol,
            )
        )
        key_buttons.append([
            InlineKeyboardButton(
                text=f"{status_emoji} {key['display_name']}",
                callback_data=f"key:{key['id']}",
            )
        ])

    return keys, build_my_keys_list_text(items), key_buttons


async def _render_my_keys_page(target, telegram_id: int, force_new: bool = False) -> None:
    """Рендерит страницу «Мои ключи» из таблицы pages."""
    from bot.utils.live_page_renderer import render_live_page

    keys, keys_list_text, key_buttons = await _build_my_keys_render_data(telegram_id)
    context = {'telegram_id': telegram_id}

    if not keys:
        await render_live_page(
            target,
            page_key='my_keys_empty',
            context=context,
            force_new=force_new,
        )
        return

    await render_live_page(
        target,
        page_key='my_keys',
        context=context,
        text_replacements={'%списокключей%': keys_list_text},
        prepend_buttons=key_buttons,
        force_new=force_new,
    )


async def rerender_my_keys_page_context(page_context, viewer_id: int) -> bool:
    """Перерисовывает сохранённый экран «Мои ключи» после правки через /yaa."""
    context = page_context.context or {}
    telegram_id = context.get('telegram_id') or viewer_id
    await _render_my_keys_page(page_context.message, int(telegram_id))
    return True


async def rerender_key_details_page_context(page_context, viewer_id: int) -> bool:
    """Перерисовывает сохранённую карточку ключа после правки через /yaa."""
    context = page_context.context or {}
    key_id = context.get('key_id')
    if not key_id:
        return False
    telegram_id = context.get('telegram_id') or viewer_id
    await show_key_details(int(telegram_id), int(key_id), page_context.message)
    return True


async def show_my_keys(telegram_id: int, target, is_callback: bool = True):
    """
    Общая логика для показа списка ключей.

    Args:
        telegram_id: ID пользователя в Telegram
        target: Message или CallbackQuery для отправки/редактирования
        is_callback: True если вызвано из callback (редактируем), False если из команды (отправляем новое)
    """
    await _render_my_keys_page(target, telegram_id, force_new=not is_callback)

@router.callback_query(F.data == 'my_keys')
async def my_keys_handler(callback: CallbackQuery):
    """Список VPN-ключей пользователя."""
    telegram_id = callback.from_user.id
    await show_my_keys(telegram_id, callback)
    await callback.answer()

async def show_key_details(telegram_id: int, key_id: int, message, is_callback: bool = True, prepend_text: str=''):
    """Общая логика для показа деталей ключа."""
    from database.requests import (
        get_key_details_for_user, get_key_payments_history, is_key_active,
        is_traffic_exhausted, get_active_subscription_by_key,
    )
    from bot.keyboards.user import key_manage_kb
    from bot.services.vpn_api import format_traffic
    from bot.utils.key_pages import build_key_details_replacements, keyboard_rows
    from bot.utils.live_page_renderer import render_live_page
    import logging
    logger = logging.getLogger(__name__)
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        if is_callback:
            await safe_edit_or_send(message, '❌ Ключ не найден или вы не являетесь его владельцем.')
        else:
            await safe_edit_or_send(message, '❌ Ключ не найден или вы не являетесь его владельцем.', force_new=True)
        return
    traffic_exhausted = is_traffic_exhausted(key)
    key_active = is_key_active(key)
    if traffic_exhausted:
        status = '🔴 Трафик исчерпан'
    elif key_active:
        status = '🟢 Активен'
    else:
        status = '🔴 Истёк'
    inbound_name = '—'
    protocol = '—'
    is_unconfigured = not key.get('server_id')
    traffic_used = key.get('traffic_used', 0) or 0
    traffic_limit = key.get('traffic_limit', 0) or 0
    if is_unconfigured:
        traffic_info = '⚠️ Требует настройки'
    elif traffic_limit > 0:
        used_str = format_traffic(traffic_used)
        limit_str = format_traffic(traffic_limit)
        percent = traffic_used / traffic_limit * 100 if traffic_limit > 0 else 0
        traffic_info = f'{used_str} из {limit_str} ({percent:.1f}%)'
    elif traffic_used > 0:
        traffic_info = f'{format_traffic(traffic_used)} (безлимит)'
    else:
        traffic_info = 'Безлимит'
    if key.get('sub_id'):
        # Subscription: один ключ покрывает все inbound сервера сразу
        inbound_name = 'Все протоколы'
        protocol = 'SUBSCRIPTION'
    elif key.get('server_active') and key.get('panel_email'):
        try:
            from bot.services.vpn_api import get_client
            client = await get_client(key['server_id'])
            stats = await client.get_client_stats(key['panel_email'])
            if stats:
                protocol = stats.get('protocol', 'vless').upper()
                inbound_name = stats.get('remark', 'VPN') or 'VPN'
        except Exception as e:
            logger.warning(f'Ошибка получения протокола: {e}')

    subscription = get_active_subscription_by_key(key_id)
    subscription_html = ''
    if subscription:
        if subscription.get('payment_method_id'):
            subscription_html = '🔁 <b>Автопродление:</b> включено'
        elif subscription.get('cancel_at_period_end'):
            subscription_html = '⛔ <b>Автопродление:</b> отключено, доступ действует до конца оплаченного периода'

    effective_prepend = prepend_text
    if subscription_html:
        effective_prepend = f"{prepend_text}\n{subscription_html}" if prepend_text else subscription_html

    payments = get_key_payments_history(key_id)
    replacements = build_key_details_replacements(
        key,
        payments,
        status=status,
        traffic_info=traffic_info,
        inbound_name=inbound_name,
        protocol=protocol,
        prepend_html=effective_prepend,
    )
    kb = key_manage_kb(
        key_id,
        is_unconfigured=is_unconfigured,
        is_active=key_active,
        is_traffic_exhausted=traffic_exhausted,
        has_sub_id=bool(key.get('sub_id')),
        include_navigation=False,
    )
    button_rows = keyboard_rows(kb)
    if subscription and subscription.get('payment_method_id'):
        button_rows.append([
            InlineKeyboardButton(text='⛔ Отключить автопродление', callback_data=f'key_unlink_card:{key_id}')
        ])
    await render_live_page(
        message,
        page_key='key_details',
        context={'telegram_id': telegram_id, 'key_id': key_id},
        text_replacements=replacements,
        prepend_buttons=button_rows,
        force_new=not is_callback,
    )

@router.callback_query(F.data.startswith('key_delete:'))
async def key_delete_handler(callback: CallbackQuery):
    """Удаление истекшего ключа пользователем."""
    key_id = int(callback.data.split(':')[1])
    telegram_id = callback.fromuser.id if hasattr(callback, 'fromuser') else callback.from_user.id
    from database.requests import get_key_details_for_user, delete_vpn_key
    from bot.services.vpn_api import get_client
    import logging
    logger = logging.getLogger(__name__)
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        await callback.answer('❌ Ключ не найден или вы не являетесь его владельцем.', show_alert=True)
        return
    if key['is_active']:
        await callback.answer('❌ Активные ключи нельзя удалить.', show_alert=True)
        return
    if key.get('server_id') and key.get('panel_email'):
        try:
            client = await get_client(key['server_id'])
            if key.get('sub_id'):
                # Subscription: удаляем всех клиентов с этим email на сервере
                deleted = await client.delete_clients_by_email_on_server(key['panel_email'])
                logger.info(
                    f"Subscription-ключ {key_id}: удалено {deleted} клиентов "
                    f"с email {key['panel_email']} с сервера 3X-UI"
                )
            elif key.get('panel_inbound_id') and key.get('client_uuid'):
                await client.delete_client(key['panel_inbound_id'], key['client_uuid'])
                logger.info(f"Клиент {key.get('panel_email', 'unknown')} удален с сервера 3X-UI")
        except Exception as e:
            logger.warning(f"Не удалось удалить клиента {key.get('panel_email', 'unknown')} с сервера 3X-UI: {e}")
    success = delete_vpn_key(key_id)
    if success:
        await callback.answer(f"✅ Ключ {key['display_name']} успешно удален.", show_alert=True)
        await show_my_keys(telegram_id, callback)
    else:
        await callback.answer('❌ Ошибка при удалении ключа из БД.', show_alert=True)

@router.callback_query(F.data.startswith('key:'))
async def key_details_handler(callback: CallbackQuery):
    """Детальная информация о ключе с улучшенной статистикой."""
    key_id = int(callback.data.split(':')[1])
    telegram_id = callback.from_user.id
    await show_key_details(telegram_id, key_id, callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith('key_unlink_card:'))
async def key_unlink_card_handler(callback: CallbackQuery):
    """Отключает автопродление и отвязывает сохранённый способ оплаты."""
    key_id = int(callback.data.split(':')[1])
    telegram_id = callback.from_user.id
    from database.requests import get_key_details_for_user, get_user_internal_id, unlink_subscription_payment_method_by_key

    key = get_key_details_for_user(key_id, telegram_id)
    user_id = get_user_internal_id(telegram_id)
    if not key or not user_id:
        await callback.answer('❌ Ключ не найден или вы не являетесь его владельцем.', show_alert=True)
        return

    if unlink_subscription_payment_method_by_key(key_id, user_id):
        await callback.answer('✅ Автопродление отключено', show_alert=True)
        await show_key_details(
            telegram_id,
            key_id,
            callback.message,
            prepend_text='✅ Карта отвязана. Автопродление отключено.',
        )
    else:
        await callback.answer('⚠️ Активная привязка карты не найдена.', show_alert=True)

@router.callback_query(F.data.startswith('key_show:'))
async def key_show_handler(callback: CallbackQuery):
    """Показать ключ для копирования (с QR и JSON)."""
    from database.requests import get_key_details_for_user
    from bot.keyboards.user import key_show_kb
    from bot.utils.key_sender import send_key_with_qr
    key_id = int(callback.data.split(':')[1])
    telegram_id = callback.from_user.id
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        await callback.answer('❌ Ключ не найден или вы не являетесь его владельцем.', show_alert=True)
        return
    if not key['client_uuid']:
        from bot.utils.page_renderer import render_page

        await render_page(callback, page_key='key_show_unconfigured')
        await callback.answer()
        return
    try:
        await safe_edit_or_send(callback.message, '⏳ Получение данных ключа...')
    except Exception:
        pass
    await send_key_with_qr(callback, key, key_show_kb(key_id))
    await callback.answer()


async def show_renew_payment_page(callback: CallbackQuery, key: dict, key_id: int, force_new: bool = False):
    """Показывает страницу выбора способа оплаты для продления ключа из pages."""
    from bot.utils.action_registry import SYSTEM_BUTTONS
    from bot.utils.page_renderer import render_page

    telegram_id = callback.from_user.id
    context = {
        'key_id': key_id,
        'telegram_id': telegram_id,
    }
    payment_button_ids = (
        'btn_renew_pay_crypto',
        'btn_renew_pay_stars',
        'btn_renew_pay_cards',
        'btn_renew_pay_qr',
        'btn_renew_pay_wata',
        'btn_renew_pay_platega',
        'btn_renew_pay_cardlink',
        'btn_renew_pay_demo',
        'btn_renew_pay_balance',
    )
    has_payment_method = any(
        SYSTEM_BUTTONS[button_id](context) is not None
        for button_id in payment_button_ids
    )

    if not has_payment_method:
        await render_page(
            callback,
            page_key='renew_payment_unavailable',
            context=context,
            force_new=force_new,
        )
        return

    text_replacements = {
        '%имяключа%': escape_html(key.get('display_name') or 'VPN-ключ'),
    }

    await render_page(
        callback,
        page_key='renew_payment',
        context=context,
        text_replacements=text_replacements,
        force_new=force_new,
    )


@router.callback_query(F.data.startswith('key_renew:'))
async def key_renew_select_payment(callback: CallbackQuery):
    """Выбор способа оплаты для продления (сразу, без тарифа)."""
    from database.requests import get_key_details_for_user
    key_id = int(callback.data.split(':')[1])
    telegram_id = callback.from_user.id
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        await callback.answer('❌ Ключ не найден или вы не являетесь его владельцем.', show_alert=True)
        return
    await show_renew_payment_page(callback, key, key_id)
    await callback.answer()


def _days_left_for_replace(key: dict) -> int:
    from datetime import datetime, timezone
    import math

    expires_at = key.get('expires_at')
    if not expires_at:
        return 365
    try:
        dt = datetime.fromisoformat(str(expires_at).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(1, math.ceil((dt - datetime.now(timezone.utc)).total_seconds() / 86400))
    except (TypeError, ValueError):
        return 30


async def _delete_old_key_client_best_effort(key: dict) -> None:
    old_server_id = key.get('server_id')
    old_email = key.get('panel_email')
    if not old_server_id or not old_email:
        return

    try:
        from bot.services.vpn_api import get_client

        old_client = await get_client(old_server_id)
        if key.get('sub_id') and hasattr(old_client, 'delete_clients_by_email_on_server'):
            await old_client.delete_clients_by_email_on_server(old_email)
            return

        old_inbound_id = key.get('panel_inbound_id')
        old_uuid = key.get('client_uuid')
        if old_inbound_id and old_uuid:
            await old_client.delete_client(int(old_inbound_id), old_uuid)
        elif hasattr(old_client, 'delete_clients_by_email_on_server'):
            await old_client.delete_clients_by_email_on_server(old_email)
    except Exception as e:
        logger.warning(
            "Key replace: failed to delete old panel client for key_id=%s: %s",
            key.get('id'),
            e,
        )


async def _replace_key_panel_config(callback: CallbackQuery, key: dict, server_id: int, inbound_id: int | None) -> dict:
    import uuid as _uuid
    from database.requests import get_tariff_by_id, update_vpn_key_config, get_key_details_for_user
    from bot.handlers.admin.users_keys import generate_unique_email
    from bot.services.vpn_api import get_client, is_subscription_mode, sync_key_to_panel_state

    client = await get_client(server_id)
    tariff = get_tariff_by_id(key.get('tariff_id')) if key.get('tariff_id') else None
    total_gb = int((key.get('traffic_limit') or 0) / (1024 ** 3)) if key.get('traffic_limit') else 0
    limit_ip = tariff.get('max_ips', 1) if tariff else 1
    days_left = _days_left_for_replace(key)
    panel_email = generate_unique_email({
        'telegram_id': callback.from_user.id,
        'username': callback.from_user.username,
    })

    if is_subscription_mode():
        inbounds = await client.get_inbounds()
        if not inbounds:
            raise RuntimeError('На сервере нет доступных протоколов')

        sub_id = _uuid.uuid4().hex
        first_uuid = None
        first_inbound_id = None
        created = 0
        for inbound in inbounds:
            try:
                flow = await client.get_inbound_flow(inbound['id'])
                result = await client.add_client(
                    inbound_id=inbound['id'],
                    email=panel_email,
                    total_gb=total_gb,
                    expire_days=days_left,
                    limit_ip=limit_ip,
                    enable=True,
                    tg_id=str(callback.from_user.id),
                    flow=flow,
                    sub_id=sub_id,
                )
                if first_inbound_id is None or inbound['id'] < first_inbound_id:
                    first_inbound_id = inbound['id']
                    first_uuid = result['uuid']
                created += 1
            except Exception as e:
                logger.warning(
                    "Key replace: failed to create subscription client in inbound %s for key_id=%s: %s",
                    inbound.get('id'),
                    key.get('id'),
                    e,
                )

        if not created or not first_uuid or first_inbound_id is None:
            raise RuntimeError('Не удалось создать новый ключ на выбранном сервере')

        update_vpn_key_config(
            key_id=key['id'],
            server_id=server_id,
            panel_inbound_id=first_inbound_id,
            panel_email=panel_email,
            client_uuid=first_uuid,
            sub_id=sub_id,
        )
    else:
        if inbound_id is None:
            raise RuntimeError('Не выбран протокол')

        flow = await client.get_inbound_flow(inbound_id)
        result = await client.add_client(
            inbound_id=inbound_id,
            email=panel_email,
            total_gb=total_gb,
            expire_days=days_left,
            limit_ip=limit_ip,
            enable=True,
            tg_id=str(callback.from_user.id),
            flow=flow,
        )
        update_vpn_key_config(
            key_id=key['id'],
            server_id=server_id,
            panel_inbound_id=inbound_id,
            panel_email=panel_email,
            client_uuid=result['uuid'],
            sub_id=None,
        )

    sync_stats = await sync_key_to_panel_state(key['id'])
    if not sync_stats.get('ok'):
        logger.warning("Key replace: key_id=%s synced with warnings: %s", key.get('id'), sync_stats)

    await _delete_old_key_client_best_effort(key)
    return get_key_details_for_user(key['id'], callback.from_user.id)


@router.callback_query(F.data.startswith('key_replace:'))
async def key_replace_start_handler(callback: CallbackQuery, state: FSMContext):
    """Начало процедуры замены ключа."""
    from database.requests import get_key_details_for_user, get_active_servers
    from bot.keyboards.user import replace_server_list_kb
    from bot.utils.key_pages import build_replace_server_select_data, keyboard_rows
    from bot.utils.groups import get_servers_for_key
    from bot.utils.page_renderer import render_page
    key_id = int(callback.data.split(':')[1])
    telegram_id = callback.from_user.id
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        await callback.answer('❌ Ключ не найден или вы не являетесь его владельцем.', show_alert=True)
        return
    if not key['is_active']:
        await callback.answer('⏳ Срок действия ключа истёк.\nПродлите его перед заменой.', show_alert=True)
        return
    tariff_id = key.get('tariff_id')
    servers = get_servers_for_key(tariff_id) if tariff_id else get_active_servers()
    if not servers:
        await callback.answer('❌ Нет доступных серверов', show_alert=True)
        return
    await state.set_state(ReplaceKey.users_server)
    await state.update_data(replace_key_id=key_id)
    await render_page(
        callback,
        page_key='key_replace_server_select',
        text_replacements={'%данныеэкрана%': build_replace_server_select_data()},
        prepend_buttons=keyboard_rows(replace_server_list_kb(servers, key_id)),
    )
    await callback.answer()


@router.callback_query(ReplaceKey.users_inbound, F.data.startswith('replace_inbound:'))
async def key_replace_inbound_handler(callback: CallbackQuery, state: FSMContext):
    from database.requests import get_key_details_for_user, get_server_by_id
    from bot.keyboards.user import replace_confirm_kb
    from bot.utils.key_pages import REPLACE_DATA_PLACEHOLDER, build_replace_confirm_data, keyboard_rows
    from bot.utils.page_renderer import render_page

    inbound_id = int(callback.data.split(':')[1])
    data = await state.get_data()
    key_id = data.get('replace_key_id')
    server_id = data.get('replace_server_id')
    key = get_key_details_for_user(key_id, callback.from_user.id)
    server = get_server_by_id(server_id)
    if not key or not server:
        await callback.answer('❌ Данные замены устарели. Начните замену заново.', show_alert=True)
        await state.clear()
        return

    await state.update_data(replace_inbound_id=inbound_id)
    await state.set_state(ReplaceKey.confirm)
    await render_page(
        callback,
        page_key='key_replace_confirm',
        text_replacements={REPLACE_DATA_PLACEHOLDER: build_replace_confirm_data(key, server, subscription_mode=False)},
        prepend_buttons=keyboard_rows(replace_confirm_kb(int(key_id))),
    )
    await callback.answer()


@router.callback_query(ReplaceKey.confirm, F.data == 'replace_confirm')
async def key_replace_confirm_handler(callback: CallbackQuery, state: FSMContext):
    from database.requests import get_key_details_for_user
    from bot.keyboards.user import key_issued_kb
    from bot.utils.key_sender import send_key_with_qr

    data = await state.get_data()
    key_id = data.get('replace_key_id')
    server_id = data.get('replace_server_id')
    inbound_id = data.get('replace_inbound_id')

    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key or not server_id:
        await callback.answer('❌ Данные замены устарели. Начните замену заново.', show_alert=True)
        await state.clear()
        return

    await safe_edit_or_send(callback.message, '⏳ Заменяем ключ...')
    try:
        new_key = await _replace_key_panel_config(
            callback=callback,
            key=key,
            server_id=int(server_id),
            inbound_id=int(inbound_id) if inbound_id else None,
        )
        await state.clear()
        await callback.answer('✅ Ключ заменён')
        await send_key_with_qr(callback, new_key, key_issued_kb(), is_new=False)
    except Exception as e:
        logger.error("Key replace failed for key_id=%s: %s", key_id, e)
        await callback.answer('❌ Не удалось заменить ключ', show_alert=True)
        await safe_edit_or_send(
            callback.message,
            f'❌ Не удалось заменить ключ: {escape_html(str(e))}\n\nПопробуйте ещё раз или обратитесь в поддержку.'
        )

@router.callback_query(ReplaceKey.users_server, F.data.startswith('replace_server:'))
async def key_replace_server_handler(callback: CallbackQuery, state: FSMContext):
    """Выбор сервера для замены."""
    from database.requests import get_server_by_id, get_key_details_for_user
    from bot.services.vpn_api import get_client, VPNAPIError, is_subscription_mode
    from bot.keyboards.user import replace_inbound_list_kb, replace_confirm_kb
    from bot.utils.key_pages import REPLACE_DATA_PLACEHOLDER, build_replace_confirm_data, build_server_screen_data, keyboard_rows
    from bot.utils.page_renderer import render_page
    server_id = int(callback.data.split(':')[1])
    server = get_server_by_id(server_id)
    if not server:
        await callback.answer('Сервер не найден', show_alert=True)
        return
    await state.update_data(replace_server_id=server_id)
    data = await state.get_data()

    # Subscription mode: пропускаем выбор inbound — сразу подтверждение
    if is_subscription_mode():
        key_id = data.get('replace_key_id')
        key = get_key_details_for_user(key_id, callback.from_user.id)
        if not key:
            await callback.answer('❌ Ключ не найден', show_alert=True)
            return
        # Минимальная проба сервера (получим inbounds позже при выполнении)
        await state.update_data(replace_inbound_id=0)
        await state.set_state(ReplaceKey.confirm)
        await render_page(
            callback,
            page_key='key_replace_confirm',
            text_replacements={
                '%данныезамены%': build_replace_confirm_data(key, server, subscription_mode=True)
            },
            prepend_buttons=keyboard_rows(replace_confirm_kb(key_id)),
        )
        await callback.answer()
        return

    # Обычный режим — выбираем inbound
    try:
        client = await get_client(server_id)
        inbounds = await client.get_inbounds()
    except Exception as e:
        logger.error(f"Ошибка получения inbound: {e}")
        await callback.answer('Ошибка подключения к серверу', show_alert=True)
        return

    if not inbounds:
        await callback.answer('❌ На сервере нет доступных протоколов', show_alert=True)
        return

    key_id = int(data.get('replace_key_id'))
    if len(inbounds) == 1:
        key = get_key_details_for_user(key_id, callback.from_user.id)
        if not key:
            await callback.answer('❌ Ключ не найден', show_alert=True)
            return
        await state.update_data(replace_inbound_id=inbounds[0]['id'])
        await state.set_state(ReplaceKey.confirm)
        await render_page(
            callback,
            page_key='key_replace_confirm',
            text_replacements={REPLACE_DATA_PLACEHOLDER: build_replace_confirm_data(key, server, subscription_mode=False)},
            prepend_buttons=keyboard_rows(replace_confirm_kb(key_id)),
        )
        await callback.answer()
        return

    await state.set_state(ReplaceKey.users_inbound)
    await render_page(
        callback,
        page_key='key_replace_inbound_select',
        text_replacements={'%данныеэкрана%': build_server_screen_data(server)},
        prepend_buttons=keyboard_rows(replace_inbound_list_kb(inbounds, key_id)),
    )
    await callback.answer()
