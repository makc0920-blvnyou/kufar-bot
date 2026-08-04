import asyncio
import os
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config import BOT_TOKEN, CHECK_LOOP_SECONDS
from database.db import init_db
from bot.middlewares.auth import AuthMiddleware, ThrottlingMiddleware
from scheduler.manager import check_all_users

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
    scheduler.start()
    logger.info(f"✅ Планировщик: цикл каждые {CHECK_LOOP_SECONDS} сек")

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
