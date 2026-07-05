"""Дополнительные обработчики ключей.

Файл восстановительно содержит хвостовые обработчики замены и переименования ключа.
Подключается перед keys.py, чтобы состояние ReplaceKey.users_server обрабатывалось полной версией.
"""
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.states.user_states import ReplaceKey, RenameKey
from bot.utils.text import escape_html, safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(ReplaceKey.users_server, F.data.startswith('replace_server:'))
async def key_replace_server_handler(callback: CallbackQuery, state: FSMContext):
    """Выбор сервера для замены."""
    from database.requests import get_server_by_id, get_key_details_for_user
    from bot.services.vpn_api import get_client, VPNAPIError, is_subscription_mode
    from bot.keyboards.user import replace_inbound_list_kb, replace_confirm_kb
    from bot.utils.key_pages import build_replace_confirm_data, build_server_screen_data, keyboard_rows
    from bot.utils.page_renderer import render_page

    server_id = int(callback.data.split(':')[1])
    server = get_server_by_id(server_id)
    if not server:
        await callback.answer('Сервер не найден', show_alert=True)
        return
    await state.update_data(replace_server_id=server_id)

    if is_subscription_mode():
        data = await state.get_data()
        key_id = data.get('replace_key_id')
        key = get_key_details_for_user(key_id, callback.from_user.id)
        if not key:
            await callback.answer('❌ Ключ не найден', show_alert=True)
            return
        try:
            client = await get_client(server_id)
            inbounds = await client.get_inbounds()
            if not inbounds:
                await callback.answer('❌ На сервере нет доступных протоколов', show_alert=True)
                return
        except VPNAPIError as e:
            await callback.answer(f'❌ Ошибка подключения: {e}', show_alert=True)
            return
        await state.set_state(ReplaceKey.confirm)
        await state.update_data(replace_inbound_id=None)
        await render_page(
            callback,
            page_key='key_replace_confirm',
            text_replacements={
                '%данныезамены%': build_replace_confirm_data(
                    key,
                    server,
                    subscription_mode=True,
                ),
            },
            prepend_buttons=keyboard_rows(replace_confirm_kb(key_id)),
        )
        await callback.answer()
        return

    try:
        client = await get_client(server_id)
        inbounds = await client.get_inbounds()
        if not inbounds:
            await callback.answer('❌ На сервере нет доступных протоколов', show_alert=True)
            return
        data = await state.get_data()
        key_id = data.get('replace_key_id')
        await state.set_state(ReplaceKey.users_inbound)
        await render_page(
            callback,
            page_key='key_replace_inbound_select',
            text_replacements={'%данныеэкрана%': build_server_screen_data(server)},
            prepend_buttons=keyboard_rows(replace_inbound_list_kb(inbounds, key_id)),
        )
    except VPNAPIError as e:
        await callback.answer(f'❌ Ошибка подключения: {e}', show_alert=True)
    await callback.answer()


@router.callback_query(ReplaceKey.users_inbound, F.data.startswith('replace_inbound:'))
async def key_replace_inbound_handler(callback: CallbackQuery, state: FSMContext):
    """Выбор inbound и подтверждение."""
    from database.requests import get_server_by_id, get_key_details_for_user
    from bot.keyboards.user import replace_confirm_kb
    from bot.utils.key_pages import build_replace_confirm_data, keyboard_rows
    from bot.utils.page_renderer import render_page

    inbound_id = int(callback.data.split(':')[1])
    await state.update_data(replace_inbound_id=inbound_id)
    data = await state.get_data()
    key_id = data.get('replace_key_id')
    server_id = data.get('replace_server_id')
    key = get_key_details_for_user(key_id, callback.from_user.id)
    server = get_server_by_id(server_id)
    await state.set_state(ReplaceKey.confirm)
    await render_page(
        callback,
        page_key='key_replace_confirm',
        text_replacements={
            '%данныезамены%': build_replace_confirm_data(
                key,
                server,
                subscription_mode=False,
            ),
        },
        prepend_buttons=keyboard_rows(replace_confirm_kb(key_id)),
    )
    await callback.answer()


@router.callback_query(ReplaceKey.confirm, F.data == 'replace_confirm')
async def key_replace_execute(callback: CallbackQuery, state: FSMContext):
    """Выполнение замены ключа."""
    from database.requests import get_key_details_for_user, get_server_by_id, update_vpn_key_connection
    from bot.services.vpn_api import get_client, VPNAPIError, is_subscription_mode
    from bot.handlers.admin.users_keys import generate_unique_email
    from bot.utils.key_sender import send_key_with_qr
    from bot.keyboards.user import key_issued_kb
    import uuid as _uuid

    data = await state.get_data()
    key_id = data.get('replace_key_id')
    new_server_id = data.get('replace_server_id')
    new_inbound_id = data.get('replace_inbound_id')
    telegram_id = callback.from_user.id
    current_key = get_key_details_for_user(key_id, telegram_id)
    new_server_data = get_server_by_id(new_server_id)
    if not current_key or not new_server_data:
        await callback.answer('❌ Ошибка данных', show_alert=True)
        return
    await safe_edit_or_send(callback.message, '⏳ Выполняется замена ключа...')

    subscription_mode = is_subscription_mode()
    old_had_sub = bool(current_key.get('sub_id'))
    is_same_server = current_key.get('server_id') == new_server_id

    try:
        if current_key.get('server_id') and current_key.get('server_active') and current_key.get('panel_email'):
            try:
                old_client = await get_client(current_key['server_id'])
                if old_had_sub or subscription_mode:
                    deleted = await old_client.delete_clients_by_email_on_server(current_key['panel_email'])
                    logger.info(
                        f"Старый ключ {key_id}: удалено {deleted} клиентов с email "
                        f"{current_key['panel_email']} на сервере {current_key['server_id']}"
                    )
                else:
                    await old_client.delete_client(current_key['panel_inbound_id'], current_key['client_uuid'])
                    logger.info(f"Старый ключ {key_id} успешно удалён (uuid: {current_key['client_uuid']})")
            except Exception as e:
                error_msg = str(e)
                logger.warning(f'Ошибка удаления старого ключа {key_id}: {error_msg}')
                if is_same_server and not (old_had_sub or subscription_mode):
                    if 'not found' in error_msg.lower() or 'не найден' in error_msg.lower() or 'no client remained' in error_msg.lower():
                        logger.info('Ключ не найден на сервере, считаем удаленным.')
                    else:
                        raise VPNAPIError(f'Не удалось удалить старый ключ: {error_msg}. Замена отменена во избежание дублей.')

        new_client = await get_client(new_server_id)
        user_fake_dict = {'telegram_id': telegram_id, 'username': current_key.get('username')}
        new_email = generate_unique_email(user_fake_dict)
        traffic_limit = current_key.get('traffic_limit', 0) or 0
        traffic_used = current_key.get('traffic_used', 0) or 0
        if traffic_limit > 0:
            remaining_bytes = max(0, traffic_limit - traffic_used)
            limit_gb = max(1, int(remaining_bytes / 1024 ** 3))
        else:
            remaining_bytes = 0
            limit_gb = 0
        expires_at = datetime.fromisoformat(current_key['expires_at'])
        now = datetime.now()
        delta = expires_at - now
        days_left = delta.days
        if delta.seconds > 0:
            days_left += 1
        if days_left < 1:
            days_left = 1

        limit_ip = 1
        if current_key.get('tariff_id'):
            from database.db_tariffs import get_tariff_by_id
            tariff = get_tariff_by_id(current_key['tariff_id'])
            if tariff:
                limit_ip = tariff.get('max_ips', 1)

        if subscription_mode:
            inbounds = await new_client.get_inbounds()
            if not inbounds:
                raise RuntimeError('На сервере нет доступных inbound')
            new_sub_id = _uuid.uuid4().hex
            min_inb_id = min(inb['id'] for inb in inbounds)
            first_uuid = None
            created = 0
            for inb in inbounds:
                try:
                    flow = await new_client.get_inbound_flow(inb['id'])
                    res = await new_client.add_client(
                        inbound_id=inb['id'], email=new_email,
                        total_gb=limit_gb, expire_days=days_left,
                        limit_ip=limit_ip, enable=True, tg_id=str(telegram_id),
                        flow=flow, sub_id=new_sub_id,
                    )
                    if inb['id'] == min_inb_id:
                        first_uuid = res['uuid']
                    created += 1
                except Exception as e:
                    logger.warning(
                        f"replace_execute (subscription): не удалось создать клиента "
                        f"в inbound {inb['id']}: {e}"
                    )
            if not first_uuid or created == 0:
                raise RuntimeError('Не удалось создать ни одного клиента на новом сервере')
            update_vpn_key_connection(
                key_id=key_id, server_id=new_server_id,
                panel_inbound_id=min_inb_id, panel_email=new_email,
                client_uuid=first_uuid, sub_id=new_sub_id,
            )
        else:
            flow = await new_client.get_inbound_flow(new_inbound_id)
            res = await new_client.add_client(
                inbound_id=new_inbound_id, email=new_email,
                total_gb=limit_gb, expire_days=days_left,
                limit_ip=limit_ip, enable=True, tg_id=str(telegram_id), flow=flow,
            )
            new_uuid = res['uuid']
            update_vpn_key_connection(
                key_id=key_id, server_id=new_server_id,
                panel_inbound_id=new_inbound_id, panel_email=new_email,
                client_uuid=new_uuid, sub_id=None,
            )

        if traffic_limit > 0:
            from database.requests import bulk_update_traffic
            bulk_update_traffic([(traffic_used, key_id)])
            logger.info(
                f'Перенос трафика ключа {key_id}: остаток {remaining_bytes / 1024 ** 3:.1f} ГБ, '
                f'полный тариф {traffic_limit / 1024 ** 3:.1f} ГБ, '
                f'использовано {traffic_used / 1024 ** 3:.1f} ГБ'
            )
        if subscription_mode:
            from bot.services.vpn_api import sync_key_to_panel_state
            sync_stats = await sync_key_to_panel_state(key_id)
            if not sync_stats.get('ok'):
                logger.warning(f"replace_execute: subscription-ключ {key_id} синхронизирован не полностью: {sync_stats}")

        await state.clear()
        updated_key = get_key_details_for_user(key_id, telegram_id)
        await send_key_with_qr(callback, updated_key, key_issued_kb(), is_new=True)
    except Exception as e:
        logger.error(f'Ошибка при замене ключа (user={callback.from_user.id}, key={key_id}): {e}')
        await safe_edit_or_send(callback.message, '❌ Произошла ошибка при замене ключа.\n\nПопробуйте позже или обратитесь в поддержку.')


@router.callback_query(F.data.startswith('key_rename:'))
async def key_rename_start_handler(callback: CallbackQuery, state: FSMContext):
    """Начало переименования ключа."""
    from database.requests import get_key_details_for_user
    from bot.keyboards.user import cancel_kb
    from bot.utils.key_pages import build_key_rename_data, keyboard_rows
    from bot.utils.page_renderer import render_page

    key_id = int(callback.data.split(':')[1])
    telegram_id = callback.from_user.id
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        await callback.answer('❌ Ключ не найден или вы не являетесь его владельцем.', show_alert=True)
        return
    await state.set_state(RenameKey.waiting_for_name)
    await state.update_data(key_id=key_id)
    await render_page(
        callback,
        page_key='key_rename_prompt',
        text_replacements={'%данныеключа%': build_key_rename_data(key)},
        prepend_buttons=keyboard_rows(cancel_kb(cancel_callback=f'key:{key_id}')),
    )
    await callback.answer()


@router.message(RenameKey.waiting_for_name)
async def key_rename_submit_handler(message: Message, state: FSMContext):
    """Обработка ввода нового имени ключа."""
    from database.requests import update_key_custom_name
    from bot.utils.text import get_message_text_for_storage

    data = await state.get_data()
    key_id = data.get('key_id')
    new_name = get_message_text_for_storage(message, 'plain')
    if not key_id:
        await state.clear()
        await safe_edit_or_send(message, '❌ Ошибка состояния. Попробуйте снова.')
        return
    if len(new_name) > 30:
        await safe_edit_or_send(message, '⚠️ Имя слишком длинное (макс. 30 символов). Попробуйте короче.')
        return
    success = update_key_custom_name(key_id, message.from_user.id, new_name)
    if success:
        prepend = f'✅ Ключ переименован в <b>{escape_html(new_name)}</b>'
    else:
        prepend = '❌ Не удалось переименовать ключ.'
    await state.clear()
    from bot.handlers.user.keys import show_key_details
    await show_key_details(message.from_user.id, key_id, message, is_callback=False, prepend_text=prepend)
