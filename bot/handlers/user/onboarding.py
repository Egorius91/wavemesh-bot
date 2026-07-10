"""Пошаговое подключение нового VPN-ключа."""
from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()

PLATFORM_PAGES = {
    'ios': 'onboarding_ios',
    'android': 'onboarding_android',
    'windows': 'onboarding_windows',
    'macos': 'onboarding_macos',
}

ALTERNATIVE_DOWNLOAD_PAGES = {
    'ios': 'download_ios',
    'android': 'download_android',
    'windows': 'download_windows',
    'macos': 'download_macos',
}

ISSUE_PAGES = {
    'enable': 'onboarding_issue_enable',
    'no_traffic': 'onboarding_issue_no_traffic',
    'mobile': 'onboarding_issue_mobile',
    'stale': 'onboarding_issue_stale',
}


def _get_owned_key(key_id: int, telegram_id: int) -> Optional[dict]:
    from database.requests import get_key_details_for_user

    return get_key_details_for_user(key_id, telegram_id)


def _get_available_onboarding_keys(telegram_id: int) -> list[dict]:
    """Return configured keys that can currently be used for a new connection."""
    from database.requests import get_user_keys_for_display, is_traffic_exhausted

    return [
        key
        for key in get_user_keys_for_display(telegram_id)
        if key.get('is_active')
        and key.get('server_id')
        and (key.get('client_uuid') or key.get('sub_id'))
        and not is_traffic_exhausted(key)
    ]


def _key_choice_label(key: dict) -> str:
    label = str(key.get('display_name') or f"Ключ #{key['id']}")
    if len(label) > 48:
        label = f'{label[:45]}...'
    return f'🔑 {label}'


async def _require_owned_key(callback: CallbackQuery, key_id: int) -> Optional[dict]:
    key = _get_owned_key(key_id, callback.from_user.id)
    if key:
        return key

    await callback.answer('Ключ не найден', show_alert=True)
    return None


async def start_key_onboarding(target, key_data: dict) -> None:
    """Открывает мастер сразу после создания нового ключа."""
    from bot.utils.page_renderer import render_page

    await render_page(
        target,
        page_key='onboarding_ready',
        context={'key_id': key_data['id']},
    )


def onboarding_connection_kb(
    key_id: int,
    platform: str,
    *,
    alternative: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    done_callback = 'onboarding_done_alt' if alternative else 'onboarding_done'
    help_callback = 'onboarding_help_alt' if alternative else 'onboarding_help'
    builder.row(
        InlineKeyboardButton(
            text='✅ VPN включён',
            callback_data=f'{done_callback}:{platform}:{key_id}',
        )
    )
    builder.row(
        InlineKeyboardButton(
            text='🧰 Не получается',
            callback_data=f'{help_callback}:{platform}:{key_id}',
        )
    )
    return builder.as_markup()


@router.callback_query(F.data == 'onboarding_start')
async def onboarding_start_handler(callback: CallbackQuery):
    """Starts setup from Help, selecting a key only when it is necessary."""
    from bot.utils.page_renderer import render_page

    keys = _get_available_onboarding_keys(callback.from_user.id)
    await callback.answer()

    if not keys:
        await render_page(callback, page_key='onboarding_no_available_key')
        return

    if len(keys) == 1:
        await render_page(
            callback,
            page_key='onboarding_ready',
            context={'key_id': keys[0]['id']},
        )
        return

    key_buttons = [
        [
            InlineKeyboardButton(
                text=_key_choice_label(key),
                callback_data=f"onboarding_ready:{key['id']}",
            )
        ]
        for key in keys
    ]
    await render_page(
        callback,
        page_key='onboarding_key_select',
        context={'telegram_id': callback.from_user.id},
        prepend_buttons=key_buttons,
    )


@router.callback_query(F.data.startswith('onboarding_ready:'))
async def onboarding_ready_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    key_id = int(callback.data.rsplit(':', 1)[1])
    if not await _require_owned_key(callback, key_id):
        return

    await callback.answer()
    await render_page(
        callback,
        page_key='onboarding_ready',
        context={'key_id': key_id},
    )


@router.callback_query(F.data.startswith('onboarding_platform:'))
async def onboarding_platform_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    _, platform, raw_key_id = callback.data.split(':', 2)
    key_id = int(raw_key_id)
    page_key = PLATFORM_PAGES.get(platform)
    if not page_key or not await _require_owned_key(callback, key_id):
        return

    await callback.answer()
    await render_page(
        callback,
        page_key=page_key,
        context={'key_id': key_id, 'platform': platform},
    )


@router.callback_query(F.data.startswith('onboarding_connection:'))
async def onboarding_connection_handler(callback: CallbackQuery):
    from bot.services.branding import ONBOARDING_CONNECTION_TEXT
    from bot.utils.key_sender import send_key_with_qr

    _, platform, raw_key_id = callback.data.split(':', 2)
    key_id = int(raw_key_id)
    key = await _require_owned_key(callback, key_id)
    if not key or platform not in PLATFORM_PAGES:
        return

    await callback.answer()
    await send_key_with_qr(
        callback,
        key,
        onboarding_connection_kb(key_id, platform),
        is_new=False,
        page_key='onboarding_connection',
        fallback_text=ONBOARDING_CONNECTION_TEXT,
        use_page_markup=False,
        onboarding_platform=platform,
    )


@router.callback_query(F.data.startswith('onboarding_connection_alt:'))
async def onboarding_connection_alternative_handler(callback: CallbackQuery):
    from bot.services.branding import ONBOARDING_CONNECTION_ALTERNATIVE_TEXT
    from bot.utils.key_sender import send_key_with_qr

    _, platform, raw_key_id = callback.data.split(':', 2)
    key_id = int(raw_key_id)
    key = await _require_owned_key(callback, key_id)
    if not key or platform not in PLATFORM_PAGES:
        return

    await callback.answer()
    await send_key_with_qr(
        callback,
        key,
        onboarding_connection_kb(key_id, platform, alternative=True),
        is_new=False,
        page_key='onboarding_connection_alternative',
        fallback_text=ONBOARDING_CONNECTION_ALTERNATIVE_TEXT,
        use_page_markup=False,
        onboarding_platform=platform,
    )


@router.callback_query(F.data.startswith('onboarding_alt:'))
async def onboarding_alternative_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    _, platform, raw_key_id = callback.data.split(':', 2)
    key_id = int(raw_key_id)
    page_key = ALTERNATIVE_DOWNLOAD_PAGES.get(platform)
    if not page_key or not await _require_owned_key(callback, key_id):
        return

    await callback.answer()
    await render_page(
        callback,
        page_key=page_key,
        visibility={
            'btn_back_downloads': False,
            'btn_back_main': False,
        },
        context={'key_id': key_id, 'platform': platform},
        append_buttons=[
            [
                InlineKeyboardButton(
                    text='✅ Приложение установлено',
                    callback_data=f'onboarding_connection_alt:{platform}:{key_id}',
                )
            ],
            [
                InlineKeyboardButton(
                    text='⬅️ Назад',
                    callback_data=f'onboarding_platform:{platform}:{key_id}',
                ),
                InlineKeyboardButton(
                    text='🏠 На главную',
                    callback_data='start',
                ),
            ],
        ],
    )


@router.callback_query(F.data.startswith('onboarding_advanced:'))
async def onboarding_advanced_handler(callback: CallbackQuery):
    from bot.keyboards.user import key_issued_kb
    from bot.utils.key_sender import send_key_with_qr

    key_id = int(callback.data.rsplit(':', 1)[1])
    key = await _require_owned_key(callback, key_id)
    if not key:
        return

    await callback.answer()
    await send_key_with_qr(callback, key, key_issued_kb(), is_new=False)


@router.callback_query(F.data.startswith('onboarding_help:'))
async def onboarding_help_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    _, platform, raw_key_id = callback.data.split(':', 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return

    await callback.answer()
    await render_page(
        callback,
        page_key='onboarding_troubleshoot',
        context={'key_id': key_id, 'platform': platform},
    )


@router.callback_query(F.data.startswith('onboarding_help_alt:'))
async def onboarding_help_alternative_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    _, platform, raw_key_id = callback.data.split(':', 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return

    await callback.answer()
    await render_page(
        callback,
        page_key='onboarding_troubleshoot',
        context={
            'key_id': key_id,
            'platform': platform,
            'connection_variant': 'alternative',
        },
    )


@router.callback_query(F.data.startswith('onboarding_issue:'))
async def onboarding_issue_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    _, issue, variant, platform, raw_key_id = callback.data.split(':', 4)
    key_id = int(raw_key_id)
    page_key = ISSUE_PAGES.get(issue)
    if (
        not page_key
        or variant not in {'primary', 'alt'}
        or platform not in PLATFORM_PAGES
        or not await _require_owned_key(callback, key_id)
    ):
        return

    context = {'key_id': key_id, 'platform': platform}
    if variant == 'alt':
        context['connection_variant'] = 'alternative'

    await callback.answer()
    await render_page(callback, page_key=page_key, context=context)


@router.callback_query(F.data.startswith('onboarding_done:'))
async def onboarding_done_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    _, platform, raw_key_id = callback.data.split(':', 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return

    await callback.answer()
    await render_page(
        callback,
        page_key='onboarding_success',
        context={'key_id': key_id, 'platform': platform},
    )


@router.callback_query(F.data.startswith('onboarding_done_alt:'))
async def onboarding_done_alternative_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    _, platform, raw_key_id = callback.data.split(':', 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return

    await callback.answer()
    await render_page(
        callback,
        page_key='onboarding_success',
        context={
            'key_id': key_id,
            'platform': platform,
            'connection_variant': 'alternative',
        },
    )
