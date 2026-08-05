from aiogram import Router

from bot.middlewares.page_context_reset import ResetAdminPageContextMiddleware
from bot.services.runtime_mode import saas_client_mode_enabled

from .start import router as start_router
from .keys import router as keys_router
from .onboarding import router as onboarding_router
from .referral import router as referral_router
from .payments import router as payments_router


router = Router()
router.message.outer_middleware(ResetAdminPageContextMiddleware())
router.callback_query.outer_middleware(ResetAdminPageContextMiddleware())

# Specific payment-return and SaaS checkout handlers must remain before the
# general /start and key handlers.
router.include_router(payments_router)
router.include_router(referral_router)
router.include_router(onboarding_router)
router.include_router(start_router)
router.include_router(keys_router)

if not saas_client_mode_enabled():
    # Trial activation and the local tariff purchase page are legacy
    # commercial surfaces and must not be imported in authoritative SaaS mode.
    from .trial import router as trial_router
    from .tariffs import router as tariffs_router

    router.include_router(trial_router)
    router.include_router(tariffs_router)

__all__ = ["router"]
