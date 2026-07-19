"""Guided setup for newly issued WaveMesh VPN keys.

HAPP is the primary recommended client. OneXray is kept as an explicit
secondary option for every supported platform.
"""
from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton

from bot.services.onboarding_branding import register_onboarding_pages
from bot.utils.onboarding_actions import register_onboarding_actions
from bot.utils.onboarding_callbacks import HAPP_DISTRIBUTIONS, parse_happ_callback

register_onboarding_pages()
register_onboarding_actions()

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
    """Return the primary HAPP page and distribution for a platform."""
    if platform == "ios":
        return "onboarding_happ_region", None
    distribution = HAPP_DEFAULT_DISTRIBUTIONS.get(platform)
    page_key = HAPP_INSTALL_PAGES.get((platform, distribution))
    if not page_key:
        raise ValueError(f"Unsupported onboarding platform: {platform}")
    return page_key, distribution


def get_onexray_page(platform: str) -> Optional[str]:
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
    return f"🔑 {label[:45]}..." if len(label) > 48 else f"🔑 {label}"


async def _require_owned_key(callback: CallbackQuery, key_id: int) -> Optional[dict]:
    key = _get_owned_key(key_id, callback.from_user.id)
    if key:
        return key
    await callback.answer("Ключ не найден", show_alert=True)
    return None


async def start_key_onboarding(target, key_data: dict) -> None:
    """Open the wizard immediately after a new key is created."""
    from bot.utils.page_renderer import render_page

    await render_page(
        target,
        page_key="onboarding_ready",
        context={"key_id": key_data["id"]},
    )


async def _render_happ_entry(callback: CallbackQuery, key_id: int, platform: str) -> None:
    from bot.utils.page_renderer import render_page

    page_key, distribution = get_primary_happ_target(platform)
    await render_page(
        callback,
        page_key=page_key,
        context={
            "key_id": key_id,
            "platform": platform,
            "app": "happ",
            "distribution": distribution,
            "region": distribution if platform == "ios" else None,
        },
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
    await render_page(
        callback,
        page_key="onboarding_key_select",
        context={"telegram_id": callback.from_user.id},
        prepend_buttons=[[
            InlineKeyboardButton(
                text=_key_choice_label(key),
                callback_data=f"onboarding_ready:{key['id']}",
            )
        ] for key in keys],
    )


@router.callback_query(F.data.startswith("onboarding_ready:"))
async def onboarding_ready_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    key_id = int(callback.data.rsplit(":", 1)[1])
    if not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await render_page(callback, page_key="onboarding_ready", context={"key_id": key_id})


@router.callback_query(F.data.startswith("onboarding_platform:"))
async def onboarding_platform_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await _render_happ_entry(callback, key_id, platform)


@router.callback_query(F.data.startswith("onboarding_alt:"))
@router.callback_query(F.data.startswith("onboarding_alt_other:"))
async def onboarding_onexray_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    key_id = int(raw_key_id)
    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    await callback.answer()
    await _render_onexray_entry(callback, key_id, platform)


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
    )


@router.callback_query(F.data.startswith("onboarding_happ_connection:"))
async def onboarding_happ_connection_handler(callback: CallbackQuery):
    from bot.services import onboarding_branding as copy
    from bot.utils.onboarding_delivery import send_onboarding_connection

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
        "ios": copy.ONBOARDING_HAPP_CONNECTION_TEXT,
        "android": copy.ONBOARDING_HAPP_CONNECTION_ANDROID_TEXT,
        "windows": copy.ONBOARDING_HAPP_CONNECTION_WINDOWS_TEXT,
        "macos": copy.ONBOARDING_HAPP_CONNECTION_MACOS_TEXT,
    }[platform]
    context = {
        "key_id": key_id,
        "platform": platform,
        "app": "happ",
        "region": distribution if platform == "ios" else None,
        "distribution": distribution,
    }
    await callback.answer()
    await send_onboarding_connection(
        callback,
        key,
        page_key=page_key,
        fallback_text=fallback_text,
        context=context,
    )


async def _send_onexray_connection(callback: CallbackQuery, platform: str, key_id: int) -> None:
    from bot.services.onboarding_branding import ONBOARDING_ONEXRAY_CONNECTION_TEXT
    from bot.utils.onboarding_delivery import send_onboarding_connection

    key = await _require_owned_key(callback, key_id)
    if not key or platform not in PLATFORM_PAGES:
        return
    context = {
        "key_id": key_id,
        "platform": platform,
        "app": "onexray",
        "connection_variant": "alternative",
    }
    await callback.answer()
    await send_onboarding_connection(
        callback,
        key,
        page_key="onboarding_onexray_connection",
        fallback_text=ONBOARDING_ONEXRAY_CONNECTION_TEXT,
        context=context,
    )


@router.callback_query(F.data.startswith("onboarding_connection:"))
@router.callback_query(F.data.startswith("onboarding_connection_alt:"))
async def onboarding_onexray_connection_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _send_onexray_connection(callback, platform, int(raw_key_id))


@router.callback_query(F.data.startswith("onboarding_advanced:"))
async def onboarding_advanced_handler(callback: CallbackQuery):
    from bot.keyboards.user import key_issued_kb
    from bot.utils.key_sender_core import send_key_with_qr

    key_id = int(callback.data.rsplit(":", 1)[1])
    key = await _require_owned_key(callback, key_id)
    if not key:
        return
    await callback.answer()
    await send_key_with_qr(callback, key, key_issued_kb(), is_new=False)


async def _render_help(
    callback: CallbackQuery,
    platform: str,
    key_id: int,
    *,
    app: str,
    distribution: str | None = None,
) -> None:
    from bot.utils.page_renderer import render_page

    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    context = {"key_id": key_id, "platform": platform, "app": app}
    if app == "happ":
        context.update({
            "distribution": distribution,
            "region": distribution if platform == "ios" else None,
        })
    else:
        context["connection_variant"] = "alternative"
    await callback.answer()
    await render_page(callback, page_key="onboarding_troubleshoot", context=context)


@router.callback_query(F.data.startswith("onboarding_happ_help:"))
async def onboarding_happ_help_handler(callback: CallbackQuery):
    parsed = parse_happ_callback(callback.data)
    if not parsed:
        await callback.answer("Некорректный шаг настройки", show_alert=True)
        return
    platform, distribution, key_id = parsed
    await _render_help(
        callback,
        platform,
        key_id,
        app="happ",
        distribution=distribution,
    )


@router.callback_query(F.data.startswith("onboarding_help:"))
@router.callback_query(F.data.startswith("onboarding_help_alt:"))
async def onboarding_onexray_help_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _render_help(callback, platform, int(raw_key_id), app="onexray")


@router.callback_query(F.data.startswith("onboarding_issue:"))
async def onboarding_issue_handler(callback: CallbackQuery):
    from bot.utils.page_renderer import render_page

    parts = callback.data.split(":")
    if len(parts) == 6 and parts[2] == "happ":
        _, issue, _, platform, distribution, raw_key_id = parts
        app = "happ"
    elif len(parts) == 5:
        _, issue, _, platform, raw_key_id = parts
        distribution = None
        app = "onexray"
    else:
        await callback.answer("Некорректный шаг настройки", show_alert=True)
        return
    key_id = int(raw_key_id)
    page_key = ISSUE_PAGES.get(issue)
    if (
        not page_key
        or platform not in PLATFORM_PAGES
        or (
            app == "happ"
            and distribution not in HAPP_DISTRIBUTIONS.get(platform, set())
        )
        or not await _require_owned_key(callback, key_id)
    ):
        return
    context = {"key_id": key_id, "platform": platform, "app": app}
    if app == "happ":
        context.update({
            "distribution": distribution,
            "region": distribution if platform == "ios" else None,
        })
    else:
        context["connection_variant"] = "alternative"
    await callback.answer()
    await render_page(callback, page_key=page_key, context=context)


async def _render_success(
    callback: CallbackQuery,
    platform: str,
    key_id: int,
    *,
    app: str,
    distribution: str | None = None,
) -> None:
    from bot.utils.page_renderer import render_page

    if platform not in PLATFORM_PAGES or not await _require_owned_key(callback, key_id):
        return
    context = {"key_id": key_id, "platform": platform, "app": app}
    if app == "happ":
        context.update({
            "distribution": distribution,
            "region": distribution if platform == "ios" else None,
        })
    else:
        context["connection_variant"] = "alternative"
    await callback.answer()
    await render_page(callback, page_key="onboarding_success", context=context)


@router.callback_query(F.data.startswith("onboarding_happ_done:"))
async def onboarding_happ_done_handler(callback: CallbackQuery):
    parsed = parse_happ_callback(callback.data)
    if not parsed:
        await callback.answer("Некорректный шаг настройки", show_alert=True)
        return
    platform, distribution, key_id = parsed
    await _render_success(
        callback,
        platform,
        key_id,
        app="happ",
        distribution=distribution,
    )


@router.callback_query(F.data.startswith("onboarding_done:"))
@router.callback_query(F.data.startswith("onboarding_done_alt:"))
async def onboarding_onexray_done_handler(callback: CallbackQuery):
    _, platform, raw_key_id = callback.data.split(":", 2)
    await _render_success(callback, platform, int(raw_key_id), app="onexray")
