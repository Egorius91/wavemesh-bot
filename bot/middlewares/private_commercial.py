"""Reject non-private SaaS updates before local or upstream user side effects."""
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

from bot.services.private_chat import private_actor_id
from bot.services.runtime_mode import saas_client_mode_enabled


class PrivateCommercialMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not saas_client_mode_enabled() or private_actor_id(event) is not None:
            return await handler(event, data)
        # No public response, unsolicited DM, raw update logging or DB/API work.
        # A callback popup is visible only to the actor who clicked the button.
        if isinstance(event, CallbackQuery):
            try:
                await event.answer("Откройте личный чат с ботом.", show_alert=True)
            except Exception:
                pass
        return None


def install_private_commercial_boundary(dispatcher):
    """Install before any message/callback middleware that can have side effects."""
    boundary = PrivateCommercialMiddleware()
    dispatcher.message.outer_middleware(boundary)
    dispatcher.callback_query.outer_middleware(boundary)
