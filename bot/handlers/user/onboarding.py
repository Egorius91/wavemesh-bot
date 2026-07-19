"""Guided setup for newly issued WaveMesh VPN keys.

HAPP is the primary recommended client. OneXray remains available as an
explicit secondary option without exposing raw connection details first.
"""
from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.utils.onboarding_callbacks import HAPP_DISTRIBUTIONS, parse_happ_callback

router = Router()

PLATFORM_PAGES = {
    "ios": "onboarding_ios",
    "android": "onboarding_android",
    "windows": "onboarding_windows",
    "macos": "onboarding_macos",
}

HAPP_DEFAULT_DISTRIBUTIONS = {
    "android": "google_play",
    "windows": "windows",
    "macos": "macos",
}

HAPP_INSTALL_PAGES = {
    ("ios", "ru"): "onboarding_happ_install_ru",
    ("ios", "global"): "onboarding_happ_install_global",
    ("android", "google_play"): "onboarding_happ_install_android",
    ("windows", "windows"): "onboarding_happ_install_windows",
    ("macos", "macos"): "onboarding_happ_install_macos",
}

HAPP_CONNECTION_PAGES = {
    "ios": "onboarding_happ_connection",
    "android": "onboarding_happ_connection_android",
    "windows": "onboarding_happ_connection_windows",
    "macos": "onboarding_happ_connection_macos",
}

ISSUE_PAGES = {
    "enable": "onboarding_issue_enable",
    "no_traffic": "onboarding_issue_no_traffic",
    "mobile": "onboarding_issue_mobile",
    "stale": "onboarding_issue_stale",
}


def get_primary_happ_target(platform: str) -> tuple[str, Optional[str]]:
    """Return the first HAPP page and distribution for a platform."""
    if platform == "ios":
        return "onboarding_happ_region", None
    distribution = HAPP_DEFAULT_DISTRIBUTIONS.get(platform)
    page_key = HAPP_INSTALL_PAGES.get((platform, distribution))
    if not page_key:
        raise ValueError(f"Unsupported onboarding platform: {platform}")
    return page_key, distribution


def get_onexray_page(platform: str) -> Optional[str]:
    """Return the secondary OneXray install page for a platform."""
    return PLATFORM_PAGES.get(platform)


def _get_owned_key(key_id: int, telegram_id: int) -> Optional[dict]:
    from database.requests import get_key_details_for_user

    return get_key_details_for_user(key_id, telegram_id)


def _get_available_onboarding_keys(telegram_id: int) -> list[dict]:
    from database.requests import get_user_keys_for_display, is_traffic_exhausted

    return [
        key
        for key in get_user_keys_for_display(telegram_id)
        if key.get("is_active")
        and key.get("server_id")
        and (key.get("client_uuid") or key.get("sub_id"))
        and not is_traffic_exhausted(key)
    ]


def _key_choice_label(key: dict) -> str:
    label = str(key.get("display_name") or f"Ключ #{key['id']}")
    if len(label) > 48:
        label = f"{label[:45]}..."
    return f"🔑 {label}"


async def _require_owned_key(callback: CallbackQuery, key_id: int) -> Optional[dict]:
    key = _get_owned_key(key_id, callback.from_user.id)
    if key:
        return key
    await callback.answer("Ключ не найден", show_alert=True)
    return None


def _onexray_button(platform: str, key_id: int) -> list[list[InlineKeyboardButton]]:
    return [[
        InlineKeyboardButton(
            text="OneXray — дополнительный вариант",
            callback_data=f"onboarding_alt_other:{platform}:{key_id}",
        )
    ]]


def _back_to_happ_button(platform: str, key_id: int) -> list[list[InlineKeyboardButton]]:
    return [[
        InlineKeyboardButton(
            text="⬅️ Вернуться к HAPP",
            callback_data=f"onboarding_platform:{platform}:{key_id}",
        )
    ]]


async def start_key_onboarding(target, key_data: dict) -> None:
    """Open the setup wizard immediately after a new key is issued."""
    from bot.utils.page_renderer import render_page

    await render_page(
        target,
        page_key="onboarding_ready",
        context={"key_id": key_data["id"]},
    )


def onboarding_connection_kb(
    key_id: int,
    platform: str,
    *,
    alternative: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    done_callback = "onboarding_done_alt" if alternative else "onboarding_done"
    help_callback = "onboarding_help_alt" if alternative else "onboarding_help"
    builder.row(
        InlineKeyboardButton(
            text="✅ VPN включён",
            callback_data=f"{done_callback}:{platform}:{key_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🧰 Не получается",
            callback_data=f"{help_callback}:{platform}:{key_id}",
        )
    )
    return builder.as_markup()


async def _render_happ_entry(callback: CallbackQuery, key_id: int, platform: str) -> None:
    from bot.utils.page_renderer import render_page

    page_key, distribution = get_primary_happ_target(platform)
    context = {
        "key_id": key_id,
        "platform": platform,
        "app": "happ",
        "distribution": distribution,
        "region": distribution if platform == "ios" else None,
    }
    await render_page(
        callback,
        page_key=page_key,
        context=context,
        visibility={"btn_onboarding_happ_other": False},
        append_buttons=_onexray_button(platform, key_id),
    )


async def _render_onexray_entry(callback: CallbackQuery, key_id: int, platform: str) -> None:
    from bot.utils.page_renderer import render_page

    page_key = get_onexray_page(platform)
    if not page_key:
        await callback.answer("Платформа не поддерживается", show_alert=True)
        return
    await render_page(
        callback,
        page_key=page_key,
        context={
            "key_id": key_id,
            "platform": platform,
            "app": "onexray",
            "connection_variant": "alternative",
        },
        visibility={
            f"btn_onboarding_alt_{platform}": False,
            "btn_onboarding_back": False,
        },
        append_buttons=_back_to_happ_button(platform, key_id),
    )


@router.callback_query(F.data == "onboarding_start")
async def onboarding_start_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    keys = _get_available_onboarding_keys(callback.from_user.id)
    await callback.answer()
    if not keys:
        await render_page(callback, page_key="onboarding_no_available_key")
        return
    if len(keys) == 1:
        await render_page(
            callback,
            page_key="onboarding_ready",
            context={"key_id": keys[0]["id"]},
        )
        return
    key_buttons = [[
        InlineKeyboardButton(
            text=_key_choice_label(key),
            callback_data=f"onboarding_ready:{key['id']}",
        )
    ] for key in keys]
    await render_page(
        callback,
        page_key="onboarding_key_select",
        context={"telegram_id": callback.from_user.id},
        prepend_buttons=key_buttons,
    )


@router.callback_query(F.data.startswith("onboarding_ready:"))
async def onboarding_ready_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    key_id = int(callback.data.rsplit(":", 1)[1])
    if not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await render_page(
        callback,
        page_key="onboarding_ready",
        context={"key_id": key_id},
    )


@router.callback_query(F.data.startswith("onboarding_platform:"))
async def onboarding_platform_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await _render_happ_entry(callback, key_id, platform)


@router.callback_query(F.data.startswith("onboarding_alt:"))
async def onboarding_alternative_handler(callback: CallbackQuery):
    """Backward-compatible route to the secondary OneXray path."""
    _, platform, raw_key_id = callback.data.split(":", 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await _render_onexray_entry(callback, key_id, platform)


@router.callback_query(F.data.startswith("onboarding_alt_other:"))
async def onboarding_onexray_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await _render_onexray_entry(callback, key_id, platform)


async def _send_onexray_connection(callback: CallbackQuery, platform: str, key_id: int) -> None:
    from bot.services.branding import ONBOARDING_CONNECTION_TEXT
    from bot.utils.key_sender import send_key_with_qr

    key = await _require_owned_key(callback, key_id)
    if not key or platform not in PLATFORM_PAGES:
        return
    await callback.answer()
    await send_key_with_qr(
        callback,
        key,
        onboarding_connection_kb(key_id, platform, alternative=True),
        is_new=False,
        page_key="onboarding_connection",
        fallback_text=ONBOARDING_CONNECTION_TEXT,
        use_page_markup=False,
        onboarding_platform=platform,
        onboarding_app="onexray",
    )


@router.callback_query(F.data.startswith("onboarding_connection:"))
async def onboarding_connection_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _send_onexray_connection(callback, platform, int(raw_key_id))


@router.callback_query(F.data.startswith("onboarding_connection_alt:"))
async def onboarding_connection_alternative_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _send_onexray_connection(callback, platform, int(raw_key_id))


@router.callback_query(F.data.startswith("onboarding_happ_install:"))
async def onboarding_happ_install_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    parsed = parse_happ_callback(callback.data)
    if not parsed:
        await callback.answer("Некорректный шаг настройки", show_alert=True)
        return
    platform, distribution, key_id = parsed
    page_key = HAPP_INSTALL_PAGES.get((platform, distribution))
    if not page_key or not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await render_page(
        callback,
        page_key=page_key,
        context={
            "key_id": key_id,
            "platform": platform,
            "app": "happ",
            "region": distribution if platform == "ios" else None,
            "distribution": distribution,
        },
        visibility={"btn_onboarding_happ_other": False},
        append_buttons=_onexray_button(platform, key_id),
    )


@router.callback_query(F.data.startswith("onboarding_happ_connection:"))
async def onboarding_happ_connection_handler(callback: CallbackQuery):
    from bot.services import branding
    from bot.utils.key_sender import send_key_with_qr
    from bot.utils.page_renderer import build_page_keyboard

    parsed = parse_happ_callback(callback.data)
    if not parsed:
        await callback.answer("Некорректный шаг настройки", show_alert=True)
        return
    platform, distribution, key_id = parsed
    key = await _require_owned_key(callback, key_id)
    page_key = HAPP_CONNECTION_PAGES.get(platform)
    if not key or not page_key:
        return
    fallback_text = {
        "ios": branding.ONBOARDING_HAPP_CONNECTION_TEXT,
        "android": branding.ONBOARDING_HAPP_CONNECTION_ANDROID_TEXT,
        "windows": branding.ONBOARDING_HAPP_CONNECTION_WINDOWS_TEXT,
        "macos": branding.ONBOARDING_HAPP_CONNECTION_MACOS_TEXT,
    }[platform]
    context = {
        "key_id": key_id,
        "platform": platform,
        "app": "happ",
        "region": distribution if platform == "ios" else None,
        "distribution": distribution,
    }
    await callback.answer()
    await send_key_with_qr(
        callback,
        key,
        key_manage_markup=build_page_keyboard(page_key, context=context),
        is_new=False,
        page_key=page_key,
        fallback_text=fallback_text,
        use_page_markup=True,
        onboarding_platform=platform,
        onboarding_app="happ",
        onboarding_region=distribution if platform == "ios" else None,
        onboarding_distribution=distribution,
    )


@router.callback_query(F.data.startswith("onboarding_happ_help:"))
async def onboarding_happ_help_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    parsed = parse_happ_callback(callback.data)
    if not parsed:
        await callback.answer("Некорректный шаг настройки", show_alert=True)
        return
    platform, distribution, key_id = parsed
    if not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await render_page(
        callback,
        page_key="onboarding_troubleshoot",
        context={
            "key_id": key_id,
            "platform": platform,
            "app": "happ",
            "region": distribution if platform == "ios" else None,
            "distribution": distribution,
        },
    )


@router.callback_query(F.data.startswith("onboarding_happ_done:"))
async def onboarding_happ_done_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    parsed = parse_happ_callback(callback.data)
    if not parsed:
        await callback.answer("Некорректный шаг настройки", show_alert=True)
        return
    platform, distribution, key_id = parsed
    if not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await render_page(
        callback,
        page_key="onboarding_success",
        context={
            "key_id": key_id,
            "platform": platform,
            "app": "happ",
            "region": distribution if platform == "ios" else None,
            "distribution": distribution,
        },
    )


@router.callback_query(F.data.startswith("onboarding_advanced:"))
async def onboarding_advanced_handler(callback: CallbackQuery):
    from bot.keyboards.user import key_issued_kb
    from bot.utils.key_sender import send_key_with_qr

    key_id = int(callback.data.rsplit(":", 1)[1])
    key = await _require_owned_key(callback, key_id)
    if not key:
        return
    await callback.answer()
    await send_key_with_qr(callback, key, key_issued_kb(), is_new=False)


async def _render_onexray_help(callback: CallbackQuery, platform: str, key_id: int) -> None:
    from bot.utils.page_renderer import render_page

    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await render_page(
        callback,
        page_key="onboarding_troubleshoot",
        context={
            "key_id": key_id,
            "platform": platform,
            "app": "onexray",
            "connection_variant": "alternative",
        },
    )


@router.callback_query(F.data.startswith("onboarding_help:"))
async def onboarding_help_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _render_onexray_help(callback, platform, int(raw_key_id))


@router.callback_query(F.data.startswith("onboarding_help_alt:"))
async def onboarding_help_alternative_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _render_onexray_help(callback, platform, int(raw_key_id))


@router.callback_query(F.data.startswith("onboarding_issue:"))
async def onboarding_issue_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    parts = callback.data.split(":")
    if len(parts) == 6 and parts[2] == "happ":
        _, issue, variant, platform, distribution, raw_key_id = parts
    elif len(parts) == 5:
        _, issue, variant, platform, raw_key_id = parts
        distribution = None
    else:
        await callback.answer("Некорректный шаг настройки", show_alert=True)
        return
    key_id = int(raw_key_id)
    page_key = ISSUE_PAGES.get(issue)
    if (
        not page_key
        or variant not in {"primary", "alt", "happ"}
        or platform not in PLATFORM_PAGES
        or (
            variant == "happ"
            and distribution not in HAPP_DISTRIBUTIONS.get(platform, set())
        )
        or not await _require_owned_key(callback, key_id)
    ):
        return
    context = {"key_id": key_id, "platform": platform}
    if variant == "happ":
        context.update({
            "app": "happ",
            "region": distribution if platform == "ios" else None,
            "distribution": distribution,
        })
    elif variant == "alt":
        context.update({
            "app": "onexray",
            "connection_variant": "alternative",
        })
    await callback.answer()
    await render_page(callback, page_key=page_key, context=context)


async def _render_success(callback: CallbackQuery, platform: str, key_id: int, *, onexray: bool) -> None:
    from bot.utils.page_renderer import render_page

    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    context = {"key_id": key_id, "platform": platform}
    if onexray:
        context.update({"app": "onexray", "connection_variant": "alternative"})
    await render_page(callback, page_key="onboarding_success", context=context)


@router.callback_query(F.data.startswith("onboarding_done:"))
async def onboarding_done_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _render_success(callback, platform, int(raw_key_id), onexray=True)


@router.callback_query(F.data.startswith("onboarding_done_alt:"))
async def onboarding_done_alternative_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _render_success(callback, platform, int(raw_key_id), onexray=True)
