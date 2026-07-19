"""Helpers for context-aware /yaa editing guidance."""
from __future__ import annotations

import re
from typing import Mapping, Optional

_PLACEHOLDER_RE = re.compile(r"%[^%\n]{1,80}%")


def collect_page_placeholders(
    page_key: str,
    text_replacements: Optional[Mapping[str, str]] = None,
) -> tuple[str, ...]:
    """Return placeholders used by the stored template or current render context."""
    from bot.utils.message_editor import get_message_data

    template = get_message_data(page_key).get("text") or ""
    values = list(_PLACEHOLDER_RE.findall(template))
    values.extend(
        key
        for key in (text_replacements or {})
        if isinstance(key, str) and _PLACEHOLDER_RE.fullmatch(key)
    )
    return tuple(dict.fromkeys(values))


def build_yaa_help_text(
    page_key: str,
    text_replacements: Optional[Mapping[str, str]] = None,
) -> str:
    """Build editor instructions and warn about placeholders of the current page."""
    text = (
        "📌 <b>Редактирование экрана</b>\n\n"
        "Отправьте новое сообщение боту:\n"
        "• текст — чтобы заменить текст экрана;\n"
        "• фото/видео/GIF с подписью — чтобы заменить текст и изображение."
    )
    placeholders = collect_page_placeholders(page_key, text_replacements)
    if not placeholders:
        return text

    rendered = ", ".join(f"<code>{placeholder}</code>" for placeholder in placeholders)
    return (
        f"{text}\n\n"
        "⚠️ <b>Сохраните динамические плейсхолдеры:</b> "
        f"{rendered}. Без них экран потеряет подставляемые данные."
    )
