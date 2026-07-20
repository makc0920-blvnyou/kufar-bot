from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger

from scheduler.jobs import check_kufar, get_stats

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    chat_id = message.chat.id
    username = message.from_user.username if message.from_user else "без username"
    logger.info(f"Получен /start от chat_id={chat_id} ({username})")

    stats = get_stats()
    await message.answer(
        f"👋 <b>Kufar iPhone Monitor</b>\n\n"
        f"🤖 Бот мониторит iPhone на kufar.by\n"
        f"📊 Цены для фильтра: 25 моделей\n"
        f"🔄 Проверок: {stats['check_count']} | Найдено: {stats['total_found']}\n\n"
        f"<b>Команды:</b>\n"
        f"/check — принудительная проверка\n"
        f"/stats — статистика"
    )


@router.message(Command("check"))
async def cmd_check(message: Message) -> None:
    await message.answer("🔍 Запускаю проверку...")
    result = await check_kufar(message.bot)
    await message.answer(result)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    stats = get_stats()
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"🔄 Всего проверок: {stats['check_count']}\n"
        f"📦 Найдено объявлений: {stats['total_found']}\n"
        f"⏰ Последняя проверка: {stats['last_check'] or 'нет'}\n"
        f"🔁 Интервал проверки: {stats['interval']} мин.\n"
        f"🔐 Текущая проверка: {'идёт' if stats['is_running'] else 'не активна'}"
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    stats = get_stats()
    await message.answer(
        f"📡 <b>Статус системы</b>\n\n"
        f"🔄 Планировщик: {'✅ активен' if stats['scheduler_running'] else '❌ остановлен'}\n"
        f"⏱ Интервал: {stats['interval']} мин."
    )