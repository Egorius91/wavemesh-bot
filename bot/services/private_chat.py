"""Actor and delivery-target checks for the SaaS Telegram adapter."""
from aiogram.types import CallbackQuery, Message, User


def private_message_for(target, telegram_id: int) -> Message | None:
    """Accept only an accessible private message addressed to the explicit owner.

    Outgoing bot messages are valid delivery targets; their from_user is the bot,
    not the owner. Incoming actor authentication is checked separately below.
    """
    if type(telegram_id) is not int or telegram_id <= 0:
        return None
    if isinstance(target, CallbackQuery):
        actor = target.from_user
        if (target.inline_message_id is not None or not isinstance(actor, User)
                or actor.is_bot or actor.id != telegram_id):
            return None
        target = target.message
    if (not isinstance(target, Message) or target.chat.type != "private"
            or target.chat.id != telegram_id or target.sender_chat is not None
            or target.business_connection_id is not None or target.date.timestamp() <= 0):
        return None
    return target


def private_actor_id(event) -> int | None:
    """Authenticate a human Telegram actor against this update's private chat."""
    if not isinstance(event, (Message, CallbackQuery)):
        return None
    actor = event.from_user
    if not isinstance(actor, User) or actor.is_bot:
        return None
    return actor.id if private_message_for(event, actor.id) is not None else None
