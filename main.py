import asyncio
import os
import threading

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask
from loguru import logger

from config import BOT_TOKEN, CHAT_ID, ALL_CHAT_IDS, CHECK_INTERVAL_MINUTES
from database.db import init_db
from bot.handlers import router
from scheduler.jobs import check_kufar, analyze_prices, set_scheduler_status

web_app = Flask(__name__)


@web_app.route("/")
@web_app.route("/health")
def health():
    return "OK", 200


def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


async def main() -> None:
    logger.info("Запуск Kufar iPhone Monitor")

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан в .env")
        return

    if CHAT_ID == 0:
        logger.error("CHAT_ID не задан в .env")
        return

    threading.Thread(target=run_web, daemon=True).start()

    await init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_kufar,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        args=[bot],
        id="check_kufar",
        replace_existing=True,
    )
    scheduler.add_job(
        analyze_prices,
        trigger="cron",
        hour=10,
        minute=0,
        args=[bot],
        id="analyze_prices",
        replace_existing=True,
    )
    scheduler.start()
    set_scheduler_status(True)

    logger.info(
        f"Бот запущен. Интервал проверки: {CHECK_INTERVAL_MINUTES} мин., "
        f"чаты: {ALL_CHAT_IDS}"
    )

    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Остановка бота...")
        scheduler.shutdown(wait=False)
        set_scheduler_status(False)
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
