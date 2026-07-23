"""Shadow-read SaaS dashboard for the «Мои ключи» entry points."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.services.internal_api import InternalApiError, internal_api_client
from database.requests import get_user_keys_for_display

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()


def _my_keys_trigger(event: TelegramObject) -> str | None:
    """Определяет вход в раздел «Мои ключи», не вмешиваясь в роутинг."""
    if isinstance(event, CallbackQuery):
        return "callback" if event.data == "my_keys" else None

    if isinstance(event, Message):
        text = (event.text or "").strip()
        if not text:
            return None
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        if command in {"/mykeys", "/my_keys"}:
            return "command"

    return None


def schedule_dashboard_shadow_read(*, telegram_id: int, trigger: str) -> None:
    """
    Сравнивает число локальных ключей и SaaS-доступов только в журнале.

    Пользовательский экран продолжает строиться исключительно из локальной БД.
    Ошибки SaaS или сравнения не влияют на выполнение обработчика Telegram.
    """
    if not internal_api_client.configured:
        return

    async def runner() -> None:
        try:
            local_keys = get_user_keys_for_display(telegram_id)
        except Exception:
            logger.exception(
                "WaveMesh dashboard shadow-read local lookup failed: "
                "telegram_id=%s trigger=%s",
                telegram_id,
                trigger,
            )
            return

        try:
            dashboard = await internal_api_client.get_telegram_dashboard(telegram_id)
        except InternalApiError as error:
            logger.warning(
                "WaveMesh dashboard shadow-read failed: "
                "telegram_id=%s trigger=%s code=%s status=%s retryable=%s",
                telegram_id,
                trigger,
                error.code,
                error.status,
                error.retryable,
            )
            return
        except Exception:
            logger.exception(
                "Unexpected WaveMesh dashboard shadow-read error: "
                "telegram_id=%s trigger=%s",
                telegram_id,
                trigger,
            )
            return

        accesses = dashboard.get("accesses")
        if not isinstance(accesses, list):
            logger.warning(
                "WaveMesh dashboard shadow-read invalid response: "
                "telegram_id=%s trigger=%s accesses_type=%s",
                telegram_id,
                trigger,
                type(accesses).__name__,
            )
            return

        local_count = len(local_keys)
        saas_count = len(accesses)
        status = "match" if local_count == saas_count else "mismatch"

        logger.info(
            "WaveMesh dashboard shadow-read completed: "
            "telegram_id=%s trigger=%s status=%s local_keys=%s saas_accesses=%s",
            telegram_id,
            trigger,
            status,
            local_count,
            saas_count,
        )

    task = asyncio.create_task(
        runner(),
        name=f"internal-api-dashboard-shadow-{telegram_id}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class InternalApiDashboardShadowMiddleware(BaseMiddleware):
    """Запускает dashboard shadow-read после успешного показа «Моих ключей»."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        trigger = _my_keys_trigger(event)
        result = await handler(event, data)

        if trigger:
            user = data.get("event_from_user")
            if user:
                schedule_dashboard_shadow_read(
                    telegram_id=user.id,
                    trigger=trigger,
                )

        return result
