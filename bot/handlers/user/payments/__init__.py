from aiogram import Router

from bot.services.runtime_mode import saas_client_mode_enabled


router = Router()

if saas_client_mode_enabled():
    # The authoritative SaaS surface owns checkout, renewals, replacements,
    # and exact opaque payment-return deep links. Legacy provider modules are
    # deliberately not imported in this runtime mode.
    from .payment_return import router as payment_return_router
    from .saas import router as saas_router

    router.include_router(payment_return_router)
    router.include_router(saas_router)
else:
    from .base import router as base_router
    from .balance import router as balance_router
    from .yookassa import router as yookassa_router
    from .wata import router as wata_router
    from .platega import router as platega_router
    from .cardlink import router as cardlink_router
    from .stars import router as stars_router
    from .crypto import router as crypto_router
    from .keys_config import router as keys_config_router
    from .demo import router as demo_router

    router.include_router(base_router)
    router.include_router(balance_router)
    router.include_router(yookassa_router)
    router.include_router(wata_router)
    router.include_router(platega_router)
    router.include_router(cardlink_router)
    router.include_router(stars_router)
    router.include_router(crypto_router)
    router.include_router(keys_config_router)
    router.include_router(demo_router)
