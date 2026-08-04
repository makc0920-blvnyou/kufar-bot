from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from loguru import logger

from bot.handlers.settings import show_settings_menu
from config import ACCESS_LIMITS, DEFAULT_ACCESS_LEVEL, MIN_PRICE_GLOBAL, WEBAPP_URL
from database.db import (
    MODEL_PRICES,
    add_setting,
    count_settings_for_user,
    delete_setting,
    get_settings_for_user,
    list_favorites,
    pause_all_for_user,
)
from services.analytics import format_user_stats

router = Router()

MODEL_HELP = (
    "Формат:\n"
    "/add_model <b>Модель</b> [мин_цена] [макс_цена] [интервал_сек] [город1,город2]\n\n"
    "Пример:\n"
    "/add_model iPhone 13 Pro 500 800 300 Минск,Гомель\n"
    "/add_model iPhone 15 600 1200\n\n"
    "Если цену не указать — возьму лимит по умолчанию."
)


def _limits_for(user) -> dict[str, int]:
    return ACCESS_LIMITS.get(user.access_level, ACCESS_LIMITS.get(DEFAULT_ACCESS_LEVEL, ACCESS_LIMITS["free"]))


def _find_model_name(arg: str) -> str | None:
    if arg in MODEL_PRICES:
        return arg
    arg_low = arg.lower()
    for model in MODEL_PRICES:
        if model.lower() == arg_low:
            return model
    return None


@router.message(Command("start"))
async def cmd_start(message: Message, db_user) -> None:
    from config import PENDING_LEVEL

    if db_user.access_level == PENDING_LEVEL:
        await message.answer(
            "⏳ <b>Запрос на доступ отправлен</b>\n\n"
            "Администратор рассмотрит вашу заявку.\n"
            "Как только доступ будет выдан — напишите <code>/start</code> снова."
        )
        return

    await message.answer(
        "👋 <b>Kufar iPhone Monitor</b>\n\n"
        "🤖 Мониторю iPhone на kufar.by и присылаю предложения по вашему лимиту.\n\n"
        "<b>Как начать:</b>\n"
        "1️⃣ Добавьте модель: <code>/add_model iPhone 15 600 1200</code>\n"
        "2️⃣ Смотрите свои модели: <code>/my_models</code>\n"
        "3️⃣ Настройки: <code>/settings</code>\n"
        "4️⃣ Управление в приложении: <code>/app</code>\n\n"
        "Команды: /help — список всех команд"
    )


@router.message(Command("help"))
async def cmd_help(message: Message, db_user) -> None:
    await message.answer(
        "<b>Команды:</b>\n\n"
        "/app — приложение для управления\n"
        "/settings — меню настроек\n"
        "/add_model — добавить модель для отслеживания\n"
        "/my_models — список моделей\n"
        "/remove_model — удалить модель\n"
        "/pause — остановить уведомления\n"
        "/resume — возобновить уведомления\n"
        "/check — принудительная проверка\n"
        "/saved — избранное\n"
        "/stats — моя статистика\n"
        "/help — помощь",
        disable_web_page_preview=True,
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, db_user) -> None:
    await show_settings_menu(message, db_user)


@router.message(Command("app"))
async def cmd_app(message: Message, db_user) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Открыть приложение",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )
    await message.answer(
        "🎛 <b>Управление в приложении</b>\n\n"
        "Модели, цены, города, интервалы и пауза — всё в одном окне.",
        reply_markup=keyboard,
    )


@router.message(Command("add_model"))
async def cmd_add_model(message: Message, command: CommandObject, db_user) -> None:
    args = (command.args or "").strip().split()
    if not args:
        await message.answer(f"<b>Добавление модели</b>\n\n{MODEL_HELP}")
        return

    name = _find_model_name(args[0])
    if name is None:
        known = ", ".join(MODEL_PRICES.keys())
        await message.answer(
            f"❌ Модель «{args[0]}» не найдена.\n\n<b>Известные модели:</b>\n{known}\n\n{MODEL_HELP}"
        )
        return

    limits = _limits_for(db_user)
    current_count = await count_settings_for_user(db_user.id)
    if limits["max_models"] is not None and current_count >= limits["max_models"]:
        await message.answer(
            f"❌ Достигнут лимит моделей для вашего уровня «{db_user.access_level}»: "
            f"{limits['max_models']}. Обратитесь к администратору за повышением."
        )
        return

    min_price: float | None = None
    max_price: float | None = None
    interval: int | None = None
    cities = "Минск"

    try:
        if len(args) >= 3:
            min_price = float(args[1].replace(",", "."))
            max_price = float(args[2].replace(",", "."))
        elif len(args) == 2:
            max_price = float(args[1].replace(",", "."))
        if len(args) >= 4:
            interval = int(args[3])
        if len(args) >= 5:
            cities = ",".join(args[4:]).strip(",")
    except ValueError:
        await message.answer(f"❌ Неверный формат чисел.\n\n{MODEL_HELP}")
        return

    default_max = float(MODEL_PRICES.get(name, 0))
    if min_price is None:
        min_price = MIN_PRICE_GLOBAL
    if max_price is None:
        max_price = default_max if default_max > 0 else None
    if max_price is not None and min_price > max_price:
        min_price, max_price = max_price, min_price

    if interval is None:
        interval = limits["min_interval"]

    if max_price is not None and max_price < MIN_PRICE_GLOBAL:
        await message.answer(f"❌ Максимальная цена слишком мала (минимум {MIN_PRICE_GLOBAL:.0f} BYN).")
        return

    setting = await add_setting(
        db_user.id,
        {
            "model": name,
            "min_price": min_price,
            "max_price": max_price,
            "cities": cities,
            "check_interval": interval,
        },
    )
    logger.info(f"Добавлена модель {name} для {db_user.id} (id={setting.id})")
    await message.answer(
        f"✅ <b>Модель добавлена</b>\n\n"
        f"📱 {name}\n"
        f"💰 {min_price:,.0f} – {max_price:,.0f} BYN\n"
        f"📍 {cities}\n"
        f"⏱ интервал: {interval} сек\n\n"
        f"Правило #<code>{setting.id}</code>"
    )


@router.message(Command("my_models"))
async def cmd_my_models(message: Message, db_user) -> None:
    settings = await get_settings_for_user(db_user.id)
    if not settings:
        await message.answer("📭 У вас нет отслеживаемых моделей. Добавьте: <code>/add_model iPhone 15 600 1200</code>")
        return

    lines = ["📋 <b>Ваши модели</b>\n"]
    for s in settings:
        state = "🟢" if s.is_active else "🔴"
        price = f"{s.min_price:,.0f}–{s.max_price:,.0f} BYN" if s.max_price else f"от {s.min_price:,.0f} BYN"
        lines.append(
            f"{state} <b>{s.model}</b> (#{s.id})\n"
            f"   💰 {price}\n"
            f"   📍 {s.cities}\n"
            f"   ⏱ {s.check_interval} сек"
        )
    lines.append("\nУдалить: <code>/remove_model НАЗВАНИЕ</code>")
    await message.answer("\n\n".join(lines))


@router.message(Command("remove_model"))
async def cmd_remove_model(message: Message, command: CommandObject, db_user) -> None:
    args = (command.args or "").strip().split()
    if not args:
        await message.answer("Формат: <code>/remove_model НАЗВАНИЕ</code> или <code>/remove_model #ID</code>")
        return

    settings = await get_settings_for_user(db_user.id)
    target = args[0]
    if target.startswith("#"):
        target_id = int(target[1:])
        matched = [s for s in settings if s.id == target_id]
    else:
        name = _find_model_name(target)
        matched = [s for s in settings if s.model == (name or target)]

    if not matched:
        await message.answer("❌ Правило не найдено.")
        return

    for s in matched:
        await delete_setting(s.id)
    await message.answer(f"✅ Удалено правил: {len(matched)}")


@router.message(Command("pause"))
async def cmd_pause(message: Message, db_user) -> None:
    n = await pause_all_for_user(db_user.id, paused=True)
    await message.answer(f"⏸️ Уведомления остановлены ({n} правил). Возобновить: <code>/resume</code>")


@router.message(Command("resume"))
async def cmd_resume(message: Message, db_user) -> None:
    n = await pause_all_for_user(db_user.id, paused=False)
    await message.answer(f"▶️ Уведомления возобновлены ({n} правил).")


@router.message(Command("saved"))
async def cmd_saved(message: Message, db_user) -> None:
    favorites = await list_favorites(db_user.id)
    if not favorites:
        await message.answer("⭐ Избранное пусто. Жмите «⭐ В избранное» под объявлением.")
        return

    from database.db import get_listing

    lines = ["⭐ <b>Избранное</b>\n"]
    for fav in favorites[:10]:
        listing = await get_listing(fav.listing_id)
        if listing is None:
            continue
        title = listing.title or fav.listing_id
        lines.append(f"• {title} — {listing.price or '—'}\n  {listing.url}")
    lines.append("\nПоказано первых 10.")
    await message.answer("\n\n".join(lines), disable_web_page_preview=True)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db_user) -> None:
    text = await format_user_stats(db_user)
    await message.answer(text)


@router.message(Command("check"))
async def cmd_check(message: Message, db_user) -> None:
    from scheduler.manager import check_for_user

    await message.answer("🔍 Проверяю ваши модели...")
    n = await check_for_user(message.bot, db_user.id)
    await message.answer(f"✅ Готово. Отправлено: {n}" if n else "🤷 Новых предложений нет.")
