import logging
from typing import Optional, Union

from aiogram.types import CallbackQuery, Message

from bot.utils.text import normalize_media_type, safe_edit_or_send, send_media_or_text
from database.requests import (
    clear_live_notice,
    clear_live_screen,
    get_live_notice,
    get_live_screen,
    get_setting,
    save_live_notice,
    save_live_screen,
)

logger = logging.getLogger(__name__)

LIVE_SCREEN_ENABLED_SETTING = 'live_screen_enabled'


def is_live_screen_enabled() -> bool:
    return get_setting(LIVE_SCREEN_ENABLED_SETTING, '0') == '1'


def _target_message(target: Union[CallbackQuery, Message]) -> Optional[Message]:
    return target.message if isinstance(target, CallbackQuery) else target


def _target_user_id(target: Union[CallbackQuery, Message], message: Message) -> Optional[int]:
    if isinstance(target, CallbackQuery):
        return target.from_user.id
    if message.from_user and not message.from_user.is_bot:
        return message.from_user.id
    chat = getattr(message, 'chat', None)
    if chat and getattr(chat, 'type', None) == 'private':
        return chat.id
    return None


async def _delete_previous_live_screen(
    *,
    bot,
    telegram_id: int,
) -> None:
    previous = get_live_screen(telegram_id)
    if not previous:
        return

    previous_message_id = previous.get('message_id')
    try:
        await bot.delete_message(
            chat_id=previous['chat_id'],
            message_id=previous_message_id,
        )
    except Exception as exc:
        logger.debug(
            "Could not delete previous live screen telegram_id=%s message_id=%s: %s",
            telegram_id,
            previous_message_id,
            exc,
        )


async def _delete_previous_live_notice(
    *,
    bot,
    telegram_id: int,
) -> None:
    previous = get_live_notice(telegram_id)
    if not previous:
        return

    previous_message_id = previous.get('message_id')
    try:
        await bot.delete_message(
            chat_id=previous['chat_id'],
            message_id=previous_message_id,
        )
    except Exception as exc:
        logger.debug(
            "Could not delete previous live notice telegram_id=%s message_id=%s: %s",
            telegram_id,
            previous_message_id,
            exc,
        )


async def _send_media_header(
    bot,
    *,
    chat_id: int,
    media: Union[str, object],
    media_type: Optional[str] = None,
) -> Message:
    normalized_media_type = normalize_media_type(media_type, media=media)
    if normalized_media_type == 'video':
        return await bot.send_video(chat_id=chat_id, video=media)
    if normalized_media_type == 'animation':
        return await bot.send_animation(chat_id=chat_id, animation=media)
    return await bot.send_photo(chat_id=chat_id, photo=media)


async def show_live_screen(
    target: Union[CallbackQuery, Message],
    text: str,
    *,
    reply_markup=None,
    media: Optional[Union[str, object]] = None,
    media_type: Optional[str] = None,
    screen_key: Optional[str] = None,
    force_new: bool = True,
) -> Message:
    message = _target_message(target)
    if message is None:
        raise ValueError("Live screen target has no message")

    telegram_id = _target_user_id(target, message)
    if not telegram_id or not is_live_screen_enabled():
        return await safe_edit_or_send(
            message,
            text,
            reply_markup=reply_markup,
            media=media,
            media_type=media_type,
            force_new=force_new,
        )

    if not force_new:
        rendered = await safe_edit_or_send(
            message,
            text,
            reply_markup=reply_markup,
            media=media,
            media_type=media_type,
            force_new=False,
        )
    else:
        await _delete_previous_live_notice(
            bot=message.bot,
            telegram_id=telegram_id,
        )
        clear_live_notice(telegram_id)
        await _delete_previous_live_screen(
            bot=message.bot,
            telegram_id=telegram_id,
        )
        if media is not None and media_type != 'preview':
            media_message = await _send_media_header(
                message.bot,
                chat_id=message.chat.id,
                media=media,
                media_type=media_type,
            )
            save_live_notice(
                telegram_id=telegram_id,
                chat_id=media_message.chat.id,
                message_id=media_message.message_id,
                notice_key=f'{screen_key or "live_screen"}_media',
            )
            media = None
            media_type = None

        rendered = await send_media_or_text(
            message.bot,
            chat_id=message.chat.id,
            text=text,
            reply_markup=reply_markup,
            media=media,
            media_type=media_type,
        )

    if rendered and getattr(rendered, 'message_id', None):
        save_live_screen(
            telegram_id=telegram_id,
            chat_id=rendered.chat.id,
            message_id=rendered.message_id,
            screen_key=screen_key,
        )
    return rendered


async def show_live_notice(
    target: Union[CallbackQuery, Message],
    text: str,
    *,
    reply_markup=None,
    notice_key: Optional[str] = None,
) -> Message:
    message = _target_message(target)
    if message is None:
        raise ValueError("Live notice target has no message")

    telegram_id = _target_user_id(target, message)
    if not telegram_id or not is_live_screen_enabled():
        return await safe_edit_or_send(
            message,
            text,
            reply_markup=reply_markup,
            force_new=True,
        )

    await _delete_previous_live_notice(
        bot=message.bot,
        telegram_id=telegram_id,
    )
    rendered = await safe_edit_or_send(
        message,
        text,
        reply_markup=reply_markup,
        force_new=True,
    )
    if rendered and getattr(rendered, 'message_id', None):
        save_live_notice(
            telegram_id=telegram_id,
            chat_id=rendered.chat.id,
            message_id=rendered.message_id,
            notice_key=notice_key,
        )
    return rendered


async def clear_live_screen_message(
    target: Union[CallbackQuery, Message],
    *,
    delete_message: bool = False,
) -> None:
    message = _target_message(target)
    if message is None:
        return

    telegram_id = _target_user_id(target, message)
    if not telegram_id:
        return

    if delete_message:
        await _delete_previous_live_notice(
            bot=message.bot,
            telegram_id=telegram_id,
        )
        await _delete_previous_live_screen(
            bot=message.bot,
            telegram_id=telegram_id,
        )
    clear_live_notice(telegram_id)
    clear_live_screen(telegram_id)
