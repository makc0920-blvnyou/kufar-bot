from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from database.db import get_user_price, set_user_price, get_distinct_models
from scheduler.jobs import check_kufar, get_stats

router = Router()

_model_map: dict[str, str] = {}


def _key(chat_id: int, idx: int) -> str:
    return f"{chat_id}:{idx}"


async def _build_menu_keyboard(chat_id: int) -> InlineKeyboardBuilder:
    global _model_map
    models = sorted(await get_distinct_models())

    builder = InlineKeyboardBuilder()
    for i, model in enumerate(models):
        k = _key(chat_id, i)
        _model_map[k] = model

        price = await get_user_price(chat_id, model)
        if price:
            label = f"✅ {model} — {price:,.0f} BYN"
        else:
            label = f"⬜ {model} — не задана"

        builder.button(text=label, callback_data=f"price:{k}")

    builder.adjust(1)
    return builder


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    chat_id = message.chat.id
    username = message.from_user.username if message.from_user else "без username"
    logger.info(f"Получен /start от chat_id={chat_id} ({username})")

    try:
        stats = get_stats()
        lines = [
            "👋 <b>Kufar iPhone Monitor</b>",
            "",
            "Бот мониторит iPhone на kufar.by и показывает объявления",
            "дешевле установленной вами цены.",
            "",
            "📌 <b>Как работает:</b>",
            "1️⃣ Установите цену для модели (кнопки ниже)",
            "2️⃣ Бот покажет объявления дешевле вашей цены",
            "3️⃣ Если цена не задана — все объявления приходят без фильтра",
            "",
            f"📊 Проверок: {stats['check_count']} | Найдено: {stats['total_found']}",
        ]

        builder = await _build_menu_keyboard(chat_id)
        await message.answer("\n".join(lines), reply_markup=builder.as_markup())
    except Exception as e:
        logger.exception(f"Ошибка в /start для chat_id={chat_id}: {e}")
        try:
            await message.answer("❌ Внутренняя ошибка, попробуйте /menu")
        except Exception:
            pass


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    chat_id = message.chat.id
    builder = await _build_menu_keyboard(chat_id)
    await message.answer("📱 <b>Настройка цен</b>\n\nНажмите на модель, чтобы установить цену.", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("price:"))
async def cb_select_model(callback: CallbackQuery) -> None:
    key = callback.data.removeprefix("price:")
    model = _model_map.get(key)
    if not model:
        await callback.answer("Модель устарела, откройте меню заново", show_alert=True)
        return

    chat_id = callback.message.chat.id
    current = await get_user_price(chat_id, model)

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅ Назад", callback_data="back_to_menu")

    text_parts = [
        f"📱 <b>{model}</b>",
        "",
    ]
    if current:
        text_parts.append(f"Текущая цена: <b>{current:,.0f} BYN</b>")
        text_parts.append(f"Показывать объявления <b>до {current:,.0f} BYN</b>")
        text_parts.append("")
        text_parts.append("✏️ Отправьте новую цену числом (например: 1200)")
        text_parts.append("Или нажмите <b>Удалить</b> чтобы убрать фильтр")
        builder.button(text="🗑 Удалить", callback_data=f"delete:{key}")
    else:
        text_parts.append("Цена не задана — приходят все объявления")
        text_parts.append("")
        text_parts.append("✏️ Отправьте цену числом (например: 1200)")

    text_parts.append("")
    text_parts.append("_Цена в BYN, без копеек_")

    await callback.message.edit_text("\n".join(text_parts), reply_markup=builder.as_markup())
    await callback.answer()

    _waiting_for_price[chat_id] = model


@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id
    builder = await _build_menu_keyboard(chat_id)
    await callback.message.edit_text(
        "📱 <b>Настройка цен</b>\n\nНажмите на модель, чтобы установить цену.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete:"))
async def cb_delete_price(callback: CallbackQuery) -> None:
    key = callback.data.removeprefix("delete:")
    model = _model_map.get(key)
    if not model:
        await callback.answer("Ошибка", show_alert=True)
        return

    chat_id = callback.message.chat.id
    await set_user_price(chat_id, model, 0)

    await callback.answer("✅ Фильтр удалён", show_alert=True)
    builder = await _build_menu_keyboard(chat_id)
    await callback.message.edit_text(
        "📱 <b>Настройка цен</b>\n\nНажмите на модель, чтобы установить цену.",
        reply_markup=builder.as_markup(),
    )

    _waiting_for_price.pop(chat_id, None)


_waiting_for_price: dict[int, str] = {}


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
        f"⏱ Интервал: {stats['interval']} мин.\n"
        f"📋 Ожидание следующей проверки..."
    )


@router.message(F.text.regexp(r'^\d+$'))
async def handle_price_input(message: Message) -> None:
    chat_id = message.chat.id
    model = _waiting_for_price.get(chat_id)
    if not model:
        return

    try:
        price = float(message.text.strip())
        if price <= 0:
            await message.reply("❌ Цена должна быть больше 0")
            return
    except ValueError:
        await message.reply("❌ Отправьте число (например: 1200)")
        return

    await set_user_price(chat_id, model, price)
    _waiting_for_price.pop(chat_id, None)

    builder = await _build_menu_keyboard(chat_id)
    await message.answer(
        f"✅ <b>{model}</b> — {price:,.0f} BYN\n"
        f"Буду показывать объявления <b>до {price:,.0f} BYN</b>\n\n"
        f"📱 <b>Меню</b>",
        reply_markup=builder.as_markup(),
    )


@router.callback_query()
async def cb_fallback(callback: CallbackQuery) -> None:
    await callback.answer("Меню устарело, отправьте /menu", show_alert=True)


@router.message()
async def any_message(message: Message) -> None:
    cid = message.chat.id
    logger.info(f"Необработанное сообщение от chat_id={cid}: {message.text or '(не текст)'}")