import asyncio
import os
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config import BOT_TOKEN, CHAT_ID, ALL_CHAT_IDS, CHECK_INTERVAL_MINUTES
from database.db import init_db
from bot.handlers import router
from scheduler.jobs import check_kufar

logger.remove()
logger.add(sys.stderr, level="INFO")

scheduler = AsyncIOScheduler()

async def handle_health(request):
    """Health check endpoint для Render"""
    return web.Response(text="OK")

async def init_web_server():
    """Запуск веб-сервера для health checks"""
    app = web.Application()
    app.router.add_get('/health', handle_health)
    app.router.add_get('/', handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render передаёт порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"✅ Web server запущен на порту {port}")
    logger.info(f"✅ Health check доступен: http://0.0.0.0:{port}/health")
    return runner

async def main():
    # Стартуем веб-сервер НЕМЕДЛЕННО, чтобы Render увидел порт
    web_runner = await init_web_server()

    logger.info("🚀 Запуск Kufar iPhone Monitor")
    logger.info(f"PORT из окружения: {os.environ.get('PORT', 'NOT SET')}")

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не задан в .env")
        return

    if CHAT_ID == 0:
        logger.error("❌ CHAT_ID не задан в .env")
        return

    # Инициализация БД
    await init_db()
    logger.info("✅ База данных инициализирована")

    # Создание бота
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Настройка планировщика
    scheduler.add_job(
        check_kufar,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        args=[bot],
        id="check_kufar",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"✅ Планировщик запущен (интервал: {CHECK_INTERVAL_MINUTES} мин)")

    logger.info(f"✅ Бот запущен. Чаты: {ALL_CHAT_IDS}")
    logger.info("Ожидание обновлений от Telegram...")

    try:
        # Запуск polling
        await dp.start_polling(bot, skip_updates=True)
    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
    finally:
        logger.info("⏹️  Остановка бота...")
        scheduler.shutdown(wait=False)
        await web_runner.cleanup()
        await bot.session.close()
        logger.info("✅ Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())