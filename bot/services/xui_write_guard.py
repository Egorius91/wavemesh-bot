"""Centralized read-only guard for legacy 3x-ui operations."""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable

from bot.services.panels.base import VPNAPIError
from bot.services.panels.xui import XUIClient
from bot.services.runtime_mode import legacy_xui_writes_enabled

logger = logging.getLogger(__name__)

_GUARD_INSTALLED = False
_MUTATING_PREFIXES = (
    "add_",
    "create_",
    "delete_",
    "disable_",
    "enable_",
    "extend_",
    "remove_",
    "replace_",
    "reset_",
    "revoke_",
    "set_",
    "update_",
)
_MUTATING_METHODS = {
    "add_client",
    "delete_client",
    "disable_client",
    "enable_client",
    "extend_client_expiry",
    "reset_client_traffic",
    "update_client",
    "update_client_expiry",
    "update_client_full",
    "update_client_limit",
}


def _is_mutating_method(name: str, value: Any) -> bool:
    if name.startswith("_") or not callable(value):
        return False
    return name in _MUTATING_METHODS or name.startswith(_MUTATING_PREFIXES)


def _blocked_message(method_name: str) -> str:
    return (
        "Legacy 3x-ui write blocked by WaveMesh runtime mode: "
        f"method={method_name}"
    )


def _wrap_async(method_name: str, method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    async def guarded(*args: Any, **kwargs: Any) -> Any:
        if not legacy_xui_writes_enabled():
            message = _blocked_message(method_name)
            logger.warning(message)
            raise VPNAPIError(message)
        return await method(*args, **kwargs)

    setattr(guarded, "__wavemesh_xui_write_guard__", True)
    return guarded


def _wrap_sync(method_name: str, method: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(method)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        if not legacy_xui_writes_enabled():
            message = _blocked_message(method_name)
            logger.warning(message)
            raise VPNAPIError(message)
        return method(*args, **kwargs)

    setattr(guarded, "__wavemesh_xui_write_guard__", True)
    return guarded


def install_xui_write_guard() -> int:
    """Wrap mutating XUIClient methods once and return the guarded count."""
    global _GUARD_INSTALLED

    if _GUARD_INSTALLED:
        return 0

    guarded_count = 0
    for method_name, method in list(vars(XUIClient).items()):
        if not _is_mutating_method(method_name, method):
            continue
        if getattr(method, "__wavemesh_xui_write_guard__", False):
            continue

        wrapper = (
            _wrap_async(method_name, method)
            if inspect.iscoroutinefunction(method)
            else _wrap_sync(method_name, method)
        )
        setattr(XUIClient, method_name, wrapper)
        guarded_count += 1

    _GUARD_INSTALLED = True
    logger.info(
        "WaveMesh XUI write guard installed: guarded_methods=%s writes_enabled=%s",
        guarded_count,
        legacy_xui_writes_enabled(),
    )
    return guarded_count
