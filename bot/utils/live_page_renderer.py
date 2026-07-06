import logging
from typing import Dict, List, Optional

from aiogram.types import CallbackQuery, InlineKeyboardButton

from bot.services.live_screen import is_live_screen_enabled, show_live_screen
from bot.utils.page_renderer import (
    _apply_text_replacements,
    _build_keyboard,
    _resolve_page_media_value,
    get_page_data,
)
from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)


async def render_live_page(
    target,
    page_key: str,
    visibility: Optional[Dict[str, bool]] = None,
    context: Optional[Dict] = None,
    text_replacements: Optional[Dict[str, str]] = None,
    prepend_buttons: Optional[List[List[InlineKeyboardButton]]] = None,
    append_buttons: Optional[List[List[InlineKeyboardButton]]] = None,
    force_new: bool = False,
) -> None:
    """Renders a page as the user's current live screen when the feature flag is enabled."""
    page_data = get_page_data(page_key)
    msg = target.message if isinstance(target, CallbackQuery) else target

    if page_data is None:
        logger.error("Страница '%s' не найдена в БД", page_key)
        await safe_edit_or_send(msg, "⚠️ Страница не настроена")
        return

    text = _apply_text_replacements(page_data["text"], text_replacements)
    kb = _build_keyboard(
        buttons=page_data["buttons"],
        visibility=visibility,
        context=context,
        prepend_buttons=prepend_buttons,
        append_buttons=append_buttons,
    )
    image = _resolve_page_media_value(page_data.get("image"))
    media_type = page_data.get("media_type")

    if is_live_screen_enabled():
        rendered_message = await show_live_screen(
            target,
            text,
            reply_markup=kb,
            media=image,
            media_type=media_type,
            screen_key=page_key,
            force_new=True,
        )
    else:
        rendered_message = await safe_edit_or_send(
            msg,
            text,
            reply_markup=kb,
            media=image,
            media_type=media_type,
            force_new=force_new,
        )

    try:
        from config import ADMIN_IDS
        from bot.services.page_context import remember_page_context

        if isinstance(target, CallbackQuery):
            viewer_id = target.from_user.id
        elif target.from_user and not target.from_user.is_bot:
            viewer_id = target.from_user.id
        else:
            chat = getattr(target, 'chat', None)
            viewer_id = chat.id if chat and getattr(chat, 'type', None) == 'private' else None

        if viewer_id in ADMIN_IDS:
            remember_page_context(
                viewer_id,
                page_key=page_key,
                message=rendered_message,
                visibility=visibility,
                context=context,
                text_replacements=text_replacements,
                prepend_buttons=prepend_buttons,
                append_buttons=append_buttons,
            )
    except Exception as e:
        logger.warning("Не удалось сохранить контекст live-страницы для /yaa: %s", e)
