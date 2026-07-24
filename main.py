"""
Точка входа WaveMesh Telegram бота.

Инициализирует бота, диспетчер, применяет миграции и запускает polling.
"""
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database.migrations import run_migrations
from database.access_shadow_outbox_triggers import ensure_access_shadow_outbox_triggers
from bot.services.branding import apply_wavemesh_branding_defaults

from bot.services.vpn_api import close_all_clients
from bot.services import scheduler as scheduler_module
from bot.services.expiry_notifications import check_and_send_expiry_notifications as clean_expiry_notifications
from bot.services.expired_key_reconciler import run_expired_key_reconciler
from bot.services.subscription_billing import run_subscription_billing_scheduler
from bot.services.access_shadow import schedule_access_shadow_backfill
from bot.services.access_shadow_outbox import (
    ensure_access_shadow_outbox_schema,
    start_access_shadow_outbox_worker,
    stop_access_shadow_outbox_worker,
)
from bot.services.internal_api import (
    internal_api_client,
    startup_probe as internal_api_startup_probe,
)

scheduler_module.check_and_send_expiry_notifications = clean_expiry_notifications
run_daily_tasks = scheduler_module.run_daily_tasks
run_update_check_scheduler = scheduler_module.run_update_check_scheduler
run_traffic_sync_scheduler = scheduler_module.run_traffic_sync_scheduler

from bot.handlers.user import router as user_router
from bot.handlers.admin import admin_router

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            "logs/bot.log",
            maxBytes=1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
    ]
)

logging.getLogger("aiohttp").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    """Действия при запуске бота."""
    logger.info("🚀 Бот запускается...")

    run_migrations()
    apply_wavemesh_branding_defaults()
    ensure_access_shadow_outbox_schema()
    ensure_access_shadow_outbox_triggers()

    internal_api_ready = await internal_api_startup_probe()
    if internal_api_ready:
        start_access_shadow_outbox_worker()
        schedule_access_shadow_backfill()

    bot_info = await bot.get_me()
    bot.my_username = bot_info.username
    logger.info(f"✅ Бот запущен: @{bot_info.username}")

    from bot.utils.update_block import is_update_blocked, get_blocked_message
    if is_update_blocked():
        from config import ADMIN_IDS
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder

        msg = get_blocked_message()
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="✅ OK", callback_data="dismiss_msg"))
        kb = builder.as_markup()

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=msg,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление о блокировке админу {admin_id}: {e}")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота."""
    logger.info("🛑 Бот останавливается...")

    await stop_access_shadow_outbox_worker()
    await close_all_clients()
    await internal_api_client.close()

    logger.info("✅ Бот остановлен")


async def main():
    """Главная функция запуска бота."""
    from bot.middlewares.parse_mode_fallback import SafeParseSession

    session = SafeParseSession()
    bot = Bot(token=BOT_TOKEN, session=session)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    from bot.middlewares.bot_blocked import BotBlockedResetMiddleware
    from bot.middlewares.internal_api_shadow import InternalApiDashboardShadowMiddleware

    bot_blocked_reset = BotBlockedResetMiddleware()
    internal_api_dashboard_shadow = InternalApiDashboardShadowMiddleware()

    dp.message.outer_middleware(bot_blocked_reset)
    dp.callback_query.outer_middleware(bot_blocked_reset)
    dp.message.outer_middleware(internal_api_dashboard_shadow)
    dp.callback_query.outer_middleware(internal_api_dashboard_shadow)

    dp.include_router(admin_router)
    dp.include_router(user_router)

    from aiogram.exceptions import TelegramNetworkError
    from aiogram.types import ErrorEvent

    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        exception = event.exception
        if isinstance(exception, TelegramNetworkError):
            logger.warning(f"⚠️ Нет связи с Telegram API: {exception}")
            return True
        logger.error(f"Необработанная ошибка: {exception}", exc_info=True)
        return True

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await bot.delete_webhook(drop_pending_updates=True)

    daily_tasks = asyncio.create_task(run_daily_tasks(bot))
    update_tasks = asyncio.create_task(run_update_check_scheduler(bot))
    traffic_tasks = asyncio.create_task(run_traffic_sync_scheduler(bot))
    expired_key_tasks = asyncio.create_task(run_expired_key_reconciler())
    subscription_tasks = asyncio.create_task(
        run_subscription_billing_scheduler(bot, interval_seconds=300)
    )
    background_tasks = [
        daily_tasks,
        update_tasks,
        traffic_tasks,
        expired_key_tasks,
        subscription_tasks,
    ]

    try:
        await dp.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        await close_all_clients()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Получен сигнал остановки")
