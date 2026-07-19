"""Dynamic button contracts for guided onboarding pages."""
from __future__ import annotations

from typing import Callable, Optional

from bot.utils.action_registry import ACTION_REGISTRY, SYSTEM_BUTTONS

PLATFORMS = {"ios", "android", "windows", "macos"}
DISTRIBUTIONS = {
    "ios": {"ru", "global"},
    "android": {"google_play"},
    "windows": {"windows"},
    "macos": {"macos"},
}


def _key_id(ctx: dict) -> Optional[str]:
    value = ctx.get("key_id")
    if value is None or value == "":
        return None
    return str(value)


def _platform(ctx: dict) -> Optional[str]:
    value = str(ctx.get("platform") or "").lower()
    return value if value in PLATFORMS else None


def _distribution(ctx: dict) -> Optional[str]:
    platform = _platform(ctx)
    value = str(ctx.get("distribution") or ctx.get("region") or "").lower()
    if platform and value in DISTRIBUTIONS.get(platform, set()):
        return value
    return None


def _callback(value: str | None) -> Optional[dict]:
    return {"callback_data": value} if value else None


def _happ_callback(action: str, ctx: dict) -> Optional[dict]:
    key_id = _key_id(ctx)
    platform = _platform(ctx)
    distribution = _distribution(ctx)
    if not key_id or not platform or not distribution:
        return None
    if platform == "ios":
        return _callback(f"onboarding_happ_{action}:{distribution}:{key_id}")
    return _callback(
        f"onboarding_happ_{action}:{platform}:{distribution}:{key_id}"
    )


def _platform_button(platform: str) -> Callable[[dict], Optional[dict]]:
    def resolve(ctx: dict) -> Optional[dict]:
        key_id = _key_id(ctx)
        return _callback(f"onboarding_platform:{platform}:{key_id}" if key_id else None)
    return resolve


def _resolve_advanced(ctx: dict) -> Optional[dict]:
    key_id = _key_id(ctx)
    return _callback(f"onboarding_advanced:{key_id}" if key_id else None)


def _resolve_happ_region(region: str) -> Callable[[dict], Optional[dict]]:
    def resolve(ctx: dict) -> Optional[dict]:
        key_id = _key_id(ctx)
        return _callback(f"onboarding_happ_install:{region}:{key_id}" if key_id else None)
    return resolve


def _resolve_onexray(ctx: dict) -> Optional[dict]:
    key_id = _key_id(ctx)
    platform = _platform(ctx)
    if not key_id or not platform:
        return None
    return _callback(f"onboarding_alt_other:{platform}:{key_id}")


def _resolve_back_device(ctx: dict) -> Optional[dict]:
    key_id = _key_id(ctx)
    return _callback(f"onboarding_ready:{key_id}" if key_id else None)


def _resolve_onexray_continue(ctx: dict) -> Optional[dict]:
    key_id = _key_id(ctx)
    platform = _platform(ctx)
    if not key_id or not platform:
        return None
    return _callback(f"onboarding_connection_alt:{platform}:{key_id}")


def _resolve_back_happ(ctx: dict) -> Optional[dict]:
    key_id = _key_id(ctx)
    platform = _platform(ctx)
    if not key_id or not platform:
        return None
    return _callback(f"onboarding_platform:{platform}:{key_id}")


def _resolve_continue_happ(ctx: dict) -> Optional[dict]:
    return _happ_callback("connection", ctx)


def _is_happ(ctx: dict) -> bool:
    return str(ctx.get("app") or "").lower() == "happ"


def _resolve_done(ctx: dict) -> Optional[dict]:
    if _is_happ(ctx):
        return _happ_callback("done", ctx)
    key_id = _key_id(ctx)
    platform = _platform(ctx)
    if not key_id or not platform:
        return None
    return _callback(f"onboarding_done_alt:{platform}:{key_id}")


def _resolve_problem(ctx: dict) -> Optional[dict]:
    if _is_happ(ctx):
        return _happ_callback("help", ctx)
    key_id = _key_id(ctx)
    platform = _platform(ctx)
    if not key_id or not platform:
        return None
    return _callback(f"onboarding_help_alt:{platform}:{key_id}")


def _resolve_retry_install(ctx: dict) -> Optional[dict]:
    if _is_happ(ctx):
        return _happ_callback("install", ctx)
    return _resolve_onexray(ctx)


def _resolve_retry_connection(ctx: dict) -> Optional[dict]:
    if _is_happ(ctx):
        return _happ_callback("connection", ctx)
    return _resolve_onexray_continue(ctx)


def _issue_button(issue: str) -> Callable[[dict], Optional[dict]]:
    def resolve(ctx: dict) -> Optional[dict]:
        key_id = _key_id(ctx)
        platform = _platform(ctx)
        if not key_id or not platform:
            return None
        if _is_happ(ctx):
            distribution = _distribution(ctx)
            if not distribution:
                return None
            return _callback(
                f"onboarding_issue:{issue}:happ:{platform}:{distribution}:{key_id}"
            )
        return _callback(f"onboarding_issue:{issue}:alt:{platform}:{key_id}")
    return resolve


def register_onboarding_actions() -> None:
    ACTION_REGISTRY["cmd_onboarding_start"] = "onboarding_start"
    SYSTEM_BUTTONS.update({
        "btn_onboarding_ios": _platform_button("ios"),
        "btn_onboarding_android": _platform_button("android"),
        "btn_onboarding_windows": _platform_button("windows"),
        "btn_onboarding_macos": _platform_button("macos"),
        "btn_onboarding_advanced": _resolve_advanced,
        "btn_onboarding_happ_ru": _resolve_happ_region("ru"),
        "btn_onboarding_happ_global": _resolve_happ_region("global"),
        "btn_onboarding_onexray": _resolve_onexray,
        "btn_onboarding_back_device": _resolve_back_device,
        "btn_onboarding_happ_continue": _resolve_continue_happ,
        "btn_onboarding_onexray_continue": _resolve_onexray_continue,
        "btn_onboarding_back_happ": _resolve_back_happ,
        "btn_onboarding_done": _resolve_done,
        "btn_onboarding_problem": _resolve_problem,
        "btn_onboarding_retry_install": _resolve_retry_install,
        "btn_onboarding_retry_connection": _resolve_retry_connection,
        "btn_onboarding_issue_enable": _issue_button("enable"),
        "btn_onboarding_issue_no_traffic": _issue_button("no_traffic"),
        "btn_onboarding_issue_mobile": _issue_button("mobile"),
        "btn_onboarding_issue_stale": _issue_button("stale"),
        "btn_onboarding_troubleshoot_back": _resolve_problem,
    })
