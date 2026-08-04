from aiogram import Router

from bot.handlers import admin, callbacks, user


def setup() -> Router:
    router = Router()
    router.include_router(user.router)
    router.include_router(callbacks.router)
    router.include_router(admin.router)
    return router
