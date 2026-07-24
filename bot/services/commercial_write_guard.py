"""Central guard for legacy commercial operations in SaaS client mode."""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable

from bot.services.runtime_mode import legacy_commercial_writes_enabled

logger = logging.getLogger(__name__)

_GUARD_INSTALLED = False
_BLOCKED_ASYNC_RESULT = (
    False,
    "⚠️ Legacy payment processing is disabled in WaveMesh SaaS client mode.",
    None,
)

# Public billing entry points which may create provider payments, mark orders paid,
# create/renew keys, or otherwise mutate commercial state.
_EXPLICIT_ENTRY_POINTS = {
    "process_payment_order",
    "process_crypto_payment",
    "create_yookassa_qr_payment",
    "check_yookassa_payment",
    "create_wata_payment",
    "check_wata_payment",
    "create_platega_payment",
    "check_platega_payment",
    "create_cardlink_payment",
    "check_cardlink_payment",
}


def _is_commercial_entry_point(name: str, value: Any) -> bool:
    if name.startswith("_") or not callable(value):
        return False
    if name in _EXPLICIT_ENTRY_POINTS:
        return True
    lowered = name.lower()
    return (
        (lowered.startswith("create_") or lowered.startswith("process_"))
        and ("payment" in lowered or "order" in lowered)
    )


def _blocked_message(name: str) -> str:
    return (
        "Legacy commercial operation blocked by WaveMesh runtime mode: "
        f"method={name}"
    )


def _wrap_async(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    async def guarded(*args: Any, **kwargs: Any) -> Any:
        if not legacy_commercial_writes_enabled():
            logger.warning(_blocked_message(name))
            if name.startswith("process_"):
                return _BLOCKED_ASYNC_RESULT
            raise RuntimeError(_blocked_message(name))
        return await function(*args, **kwargs)

    setattr(guarded, "__wavemesh_commercial_guard__", True)
    return guarded


def _wrap_sync(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        if not legacy_commercial_writes_enabled():
            logger.warning(_blocked_message(name))
            raise RuntimeError(_blocked_message(name))
        return function(*args, **kwargs)

    setattr(guarded, "__wavemesh_commercial_guard__", True)
    return guarded


def install_commercial_write_guard() -> int:
    """Wrap billing entry points before Telegram handlers import them."""
    global _GUARD_INSTALLED

    if _GUARD_INSTALLED:
        return 0

    from bot.services import billing

    guarded_count = 0
    for name, function in list(vars(billing).items()):
        if not _is_commercial_entry_point(name, function):
            continue
        if getattr(function, "__wavemesh_commercial_guard__", False):
            continue

        wrapper = (
            _wrap_async(name, function)
            if inspect.iscoroutinefunction(function)
            else _wrap_sync(name, function)
        )
        setattr(billing, name, wrapper)
        guarded_count += 1

    _GUARD_INSTALLED = True
    logger.info(
        "WaveMesh commercial write guard installed: guarded_methods=%s writes_enabled=%s",
        guarded_count,
        legacy_commercial_writes_enabled(),
    )
    return guarded_count
