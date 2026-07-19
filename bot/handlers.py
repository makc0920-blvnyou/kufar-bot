from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from scheduler.jobs import check_kufar, get_stats

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    stats = get_stats()
    await message.answer(
        f"👋 <b>Kufar iPhone Monitor</b>\n\n"
        f"🤖 Бот активен и мониторит новые объявления iPhone на kufar.by\n"
        f"📊 Последняя проверка: {stats['last_check'] or 'ещё не выполнялась'}\n"
        f"✅ Найдено объявлений: {stats['total_found']}\n"
        f"🔄 Проверок выполнено: {stats['check_count']}\n\n"
        f"<b>Доступные команды:</b>\n"
        f"/check — принудительная проверка\n"
        f"/stats — подробная статистика\n"
        f"/status — статус планировщика",
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
        f"🔐 Текущая проверка: {'идёт' if stats['is_running'] else 'не активна'}",
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    stats = get_stats()
    await message.answer(
        f"📡 <b>Статус системы</b>\n\n"
        f"🔄 Планировщик: {'✅ активен' if stats['scheduler_running'] else '❌ остановлен'}\n"
        f"⏱ Интервал: {stats['interval']} мин.\n"
        f"📋 Ожидание следующей проверки...",
    )
