from aiogram import Router

from bot.handlers import admin, callbacks, settings, user


def setup() -> Router:
    router = Router()
    router.include_router(user.router)
    router.include_router(settings.router)
    router.include_router(callbacks.router)
    router.include_router(admin.router)
    return router
