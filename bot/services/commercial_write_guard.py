"""Central guard for legacy commercial operations in SaaS client mode."""

from __future__ import annotations

import functools
import inspect
import logging
from types import ModuleType
from typing import Any, Callable, Iterable

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
_BILLING_ENTRY_POINTS = {
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

# Database entry points used directly by Telegram/admin handlers before billing.
# These are legacy commercial writes and must never mutate local SQLite while the
# bot is operating as a SaaS client.
_DATABASE_ENTRY_POINTS = {
    # Orders and provider context.
    "create_pending_order",
    "complete_order",
    "update_order_tariff",
    "update_payment_type",
    "update_payment_key_id",
    "save_yookassa_payment_id",
    "save_wata_payment_id",
    "save_platega_payment_id",
    "save_cardlink_payment_id",
    "save_order_subscription_context",
    # Balance and referral money.
    "add_to_balance",
    "deduct_from_balance",
    # Local key creation and commercial extension.
    "create_initial_vpn_key",
    "create_vpn_key_admin",
    "extend_vpn_key",
    "add_days_to_first_active_key",
    # Legacy subscription/payment-method state.
    "unlink_subscription_payment_method_by_key",
    # Trial activation also creates local commercial access.
    "mark_trial_used",
}

# Recurring YooKassa functions are imported directly from their service module.
_RECURRING_ENTRY_POINTS = {
    "create_yookassa_initial_subscription_payment",
    "charge_saved_payment_method",
    "create_recurring_payment",
}


def _blocked_message(name: str) -> str:
    return (
        "Legacy commercial operation blocked by WaveMesh runtime mode: "
        f"method={name}"
    )


def _wrap_async(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    async def guarded(*args: Any, **kwargs: Any) -> Any:
        if not legacy_commercial_writes_enabled():
            message = _blocked_message(name)
            logger.warning(message)
            if name.startswith("process_"):
                return _BLOCKED_ASYNC_RESULT
            raise RuntimeError(message)
        return await function(*args, **kwargs)

    setattr(guarded, "__wavemesh_commercial_guard__", True)
    return guarded


def _wrap_sync(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        if not legacy_commercial_writes_enabled():
            message = _blocked_message(name)
            logger.warning(message)
            raise RuntimeError(message)
        return function(*args, **kwargs)

    setattr(guarded, "__wavemesh_commercial_guard__", True)
    return guarded


def _guard_module_entry_points(
    module: ModuleType,
    entry_points: Iterable[str],
) -> int:
    guarded_count = 0
    for name in entry_points:
        function = getattr(module, name, None)
        if not callable(function):
            continue
        if getattr(function, "__wavemesh_commercial_guard__", False):
            continue

        wrapper = (
            _wrap_async(name, function)
            if inspect.iscoroutinefunction(function)
            else _wrap_sync(name, function)
        )
        setattr(module, name, wrapper)
        guarded_count += 1
    return guarded_count


def _discover_billing_entry_points(module: ModuleType) -> set[str]:
    names = set(_BILLING_ENTRY_POINTS)
    for name, value in vars(module).items():
        if name.startswith("_") or not callable(value):
            continue
        lowered = name.lower()
        if (
            (lowered.startswith("create_") or lowered.startswith("process_"))
            and ("payment" in lowered or "order" in lowered)
        ):
            names.add(name)
    return names


def _discover_database_entry_points(module: ModuleType) -> set[str]:
    names = set(_DATABASE_ENTRY_POINTS)
    for name, value in vars(module).items():
        if not callable(value):
            continue
        lowered = name.lower()
        if lowered.startswith("save_") and lowered.endswith("payment_id"):
            names.add(name)
    return names


def install_commercial_write_guard() -> int:
    """Wrap commercial writes before Telegram handlers import their functions."""
    global _GUARD_INSTALLED

    if _GUARD_INSTALLED:
        return 0

    from bot.services import billing
    from bot.services import yookassa_recurring
    import database.requests as database_requests

    guarded_count = 0
    guarded_count += _guard_module_entry_points(
        billing,
        _discover_billing_entry_points(billing),
    )
    guarded_count += _guard_module_entry_points(
        database_requests,
        _discover_database_entry_points(database_requests),
    )
    guarded_count += _guard_module_entry_points(
        yookassa_recurring,
        _RECURRING_ENTRY_POINTS,
    )

    _GUARD_INSTALLED = True
    logger.info(
        "WaveMesh commercial write guard installed: guarded_methods=%s writes_enabled=%s",
        guarded_count,
        legacy_commercial_writes_enabled(),
    )
    return guarded_count
