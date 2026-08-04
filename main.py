import asyncio
import os
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonWebApp, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config import BOT_TOKEN, CHECK_LOOP_SECONDS, WEBAPP_URL
from database.db import init_db
from bot.middlewares.auth import AuthMiddleware, ThrottlingMiddleware
from scheduler.manager import check_all_users
from webapp import api as webapp_api

logger.remove()
logger.add(sys.stderr, level="INFO")

scheduler = AsyncIOScheduler()

# Глобальная ссылка на бота для задач планировщика
_bot: Bot | None = None


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def init_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_health)

    app.router.add_get("/app", webapp_api.index)
    app.router.add_get("/api/init", webapp_api.api_init)
    app.router.add_get("/api/settings", webapp_api.api_settings)
    app.router.add_post("/api/settings/add", webapp_api.api_add)
    app.router.add_post("/api/settings/update", webapp_api.api_update)
    app.router.add_post("/api/settings/delete", webapp_api.api_delete)
    app.router.add_post("/api/settings/toggle", webapp_api.api_toggle)
    app.router.add_post("/api/settings/pause_all", webapp_api.api_pause_all)
    app.router.add_post("/api/settings/resume_all", webapp_api.api_resume_all)
    app.router.add_get("/api/stats", webapp_api.api_stats)
    app.router.add_get("/api/saved", webapp_api.api_saved)
    app.router.add_post("/api/saved/remove", webapp_api.api_saved_remove)
    app.router.add_post("/api/check", webapp_api.api_check)
    app.router.add_get("/api/hidden", webapp_api.api_hidden)
    app.router.add_post("/api/hidden/remove", webapp_api.api_hidden_remove)

    app.router.add_get("/api/admin/dashboard", webapp_api.api_admin_dashboard)
    app.router.add_get("/api/admin/users", webapp_api.api_admin_users)
    app.router.add_post("/api/admin/user/level", webapp_api.api_admin_user_level)
    app.router.add_post("/api/admin/user/block", webapp_api.api_admin_user_block)
    app.router.add_post("/api/admin/user/stats", webapp_api.api_admin_user_stats)
    app.router.add_post("/api/admin/grant", webapp_api.api_admin_grant)
    app.router.add_post("/api/admin/broadcast", webapp_api.api_admin_broadcast)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(f"✅ Web server на порту {port}, health: /health")
    return runner


async def scheduled_tick() -> None:
    if _bot is None:
        return
    try:
        await check_all_users(_bot)
    except Exception as e:
        logger.exception(f"Ошибка в scheduled_tick: {e}")


async def main() -> None:
    web_runner = await init_web_server()

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не задан")
        await web_runner.cleanup()
        return

    await init_db()

    bot = Bot(token=BOT_TOKEN)
    global _bot
    _bot = bot
    webapp_api.set_bot(bot)

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="⚙️ Настройки",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        )
        logger.info(f"✅ Menu button (WebApp): {WEBAPP_URL}")
    except Exception as e:
        logger.warning(f"Не удалось установить menu button: {e}")

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ThrottlingMiddleware(limit_per_min=10))
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware(limit_per_min=60))
    dp.callback_query.middleware(AuthMiddleware())

    from bot.handlers import setup as setup_routers

    dp.include_router(setup_routers())

    scheduler.add_job(
        scheduled_tick,
        trigger="interval",
        seconds=CHECK_LOOP_SECONDS,
        id="user_loop",
        replace_existing=True,
        max_instances=1,
    )

    from database.db import downgrade_expired_premiums

    async def premium_expiry_tick() -> None:
        try:
            n = await downgrade_expired_premiums()
            if n:
                logger.info(f"Premium даунгрейд: {n} пользователей → free")
        except Exception as e:
            logger.exception(f"Ошибка premium_expiry_tick: {e}")

    scheduler.add_job(
        premium_expiry_tick,
        trigger="cron",
        hour=4,
        minute=0,
        id="premium_expiry",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"✅ Планировщик: цикл каждые {CHECK_LOOP_SECONDS} сек, даунгрейд premium 04:00 UTC")

    # Сразу при старте чистим уже истёкшие premium
    asyncio.create_task(premium_expiry_tick())

    logger.info("🚀 Бот запущен. Ожидание обновлений...")
    try:
        await dp.start_polling(bot, skip_updates=True)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
    finally:
        logger.info("⏹️  Остановка...")
        scheduler.shutdown(wait=False)
        await web_runner.cleanup()
        await bot.session.close()
        logger.info("✅ Остановлен")


if __name__ == "__main__":
    asyncio.run(main())
