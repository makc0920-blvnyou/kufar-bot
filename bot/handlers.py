from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import get_user_price, set_user_price, get_distinct_models
from scheduler.jobs import check_kufar, get_stats

router = Router()

_model_map: dict[str, tuple[str, str]] = {}

BUYER_DISCOUNT = 0.1


def _key(chat_id: int, idx: int) -> str:
    return f"{chat_id}:{idx}"


async def _build_menu_keyboard(chat_id: int) -> InlineKeyboardBuilder:
    global _model_map
    models = sorted(await get_distinct_models())

    builder = InlineKeyboardBuilder()
    for i, (model, storage) in enumerate(models):
        k = _key(chat_id, i)
        _model_map[k] = (model, storage)

        price = await get_user_price(chat_id, model, storage)
        if price:
            label = f"✅ {model} {storage} — {price:,.0f} BYN"
        else:
            label = f"⬜ {model} {storage} — не задана"

        builder.button(text=label, callback_data=f"price:{k}")

    builder.adjust(1)
    return builder


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    stats = get_stats()
    chat_id = message.chat.id

    lines = [
        "👋 <b>Kufar iPhone Monitor</b>",
        "",
        "Бот мониторит iPhone на kufar.by и показывает объявления,",
        f"которые <b>минимум на {BUYER_DISCOUNT*100:.0f}%</b> дешевле вашей цены.",
        "",
        "📌 <b>Как работает:</b>",
        f"1️⃣ Установите цену для модели (кнопки ниже)",
        f"2️⃣ Бот покажет объявления дешевле вашей цены на {BUYER_DISCOUNT*100:.0f}%+",
        "3️⃣ Если цена не задана — модель не отслеживается",
        "",
        f"📊 Проверок: {stats['check_count']} | Найдено: {stats['total_found']}",
    ]

    builder = await _build_menu_keyboard(chat_id)
    await message.answer("\n".join(lines), reply_markup=builder.as_markup())


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    chat_id = message.chat.id
    builder = await _build_menu_keyboard(chat_id)
    await message.answer("📱 <b>Настройка цен</b>\n\nНажмите на модель, чтобы установить цену.", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("price:"))
async def cb_select_model(callback: CallbackQuery) -> None:
    key = callback.data.removeprefix("price:")
    pair = _model_map.get(key)
    if not pair:
        await callback.answer("Модель устарела, откройте меню заново", show_alert=True)
        return

    model, storage = pair
    chat_id = callback.message.chat.id
    current = await get_user_price(chat_id, model, storage)

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅ Назад", callback_data="back_to_menu")

    text_parts = [
        f"📱 <b>{model} {storage}</b>",
        "",
    ]
    if current:
        text_parts.append(f"Текущая цена: <b>{current:,.0f} BYN</b>")
        text_parts.append(f"Показывать объявления от <b>{current * (1 - BUYER_DISCOUNT):,.0f} BYN</b> и ниже")
        text_parts.append("")
        text_parts.append("✏️ Отправьте новую цену числом (например: 1200)")
        text_parts.append("Или нажмите <b>Удалить</b> чтобы убрать модель из отслеживания")
        builder.button(text="🗑 Удалить", callback_data=f"delete:{key}")
    else:
        text_parts.append("Цена не задана")
        text_parts.append("")
        text_parts.append("✏️ Отправьте цену числом (например: 1200)")

    text_parts.append("")
    text_parts.append("_Цена в BYN, без копеек_")

    await callback.message.edit_text("\n".join(text_parts), reply_markup=builder.as_markup())
    await callback.answer()

    _waiting_for_price[(chat_id, model, storage)] = True


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
    pair = _model_map.get(key)
    if not pair:
        await callback.answer("Ошибка", show_alert=True)
        return

    model, storage = pair
    chat_id = callback.message.chat.id
    await set_user_price(chat_id, model, storage, 0)

    await callback.answer("✅ Цена удалена", show_alert=True)
    builder = await _build_menu_keyboard(chat_id)
    await callback.message.edit_text(
        "📱 <b>Настройка цен</b>\n\nНажмите на модель, чтобы установить цену.",
        reply_markup=builder.as_markup(),
    )

    key_price = (chat_id, model, storage)
    _waiting_for_price.pop(key_price, None)


_waiting_for_price: dict[tuple[int, str, str], bool] = {}


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
    matched = None
    for (c, m, s), _ in list(_waiting_for_price.items()):
        if c == chat_id:
            matched = (m, s)
            break

    if not matched:
        return

    model, storage = matched
    try:
        price = float(message.text.strip())
        if price <= 0:
            await message.reply("❌ Цена должна быть больше 0")
            return
    except ValueError:
        await message.reply("❌ Отправьте число (например: 1200)")
        return

    await set_user_price(chat_id, model, storage, price)
    threshold = price * (1 - BUYER_DISCOUNT)

    _waiting_for_price.pop((chat_id, model, storage), None)

    builder = await _build_menu_keyboard(chat_id)
    await message.answer(
        f"✅ <b>{model} {storage}</b> — {price:,.0f} BYN\n"
        f"Буду показывать объявления от <b>{threshold:,.0f} BYN</b> и ниже\n\n"
        f"📱 <b>Меню</b>",
        reply_markup=builder.as_markup(),
    )


@router.callback_query()
async def cb_fallback(callback: CallbackQuery) -> None:
    await callback.answer("Меню устарело, отправьте /menu", show_alert=True)