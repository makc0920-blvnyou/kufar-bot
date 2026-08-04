from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.handlers.states import CitiesFlow, IntervalFlow, PriceFlow
from bot.keyboards.inline import (
    build_interval_menu,
    build_model_browser,
    build_model_detail,
    build_settings_menu,
)
from config import ACCESS_LIMITS, DEFAULT_ACCESS_LEVEL, MIN_PRICE_GLOBAL
from database.db import (
    DEFAULT_LIMIT_MODELS,
    MODEL_PRICES,
    add_setting,
    clear_settings_for_user,
    count_settings_for_user,
    delete_setting,
    get_settings_for_user,
    get_setting,
    set_setting_active,
    update_setting,
)
from services.notification import edit_message

router = Router()


def _limits_for(user) -> dict[str, int]:
    return ACCESS_LIMITS.get(user.access_level, ACCESS_LIMITS.get(DEFAULT_ACCESS_LEVEL, ACCESS_LIMITS["free"]))


def _default_max(model: str) -> float:
    return float(MODEL_PRICES.get(model, 0)) or 0.0


async def show_settings_menu(target: Message | CallbackQuery, db_user) -> None:
    settings = await get_settings_for_user(db_user.id)
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        "Ваши правила отслеживания — нажмите, чтобы изменить:"
        if settings
        else "⚙️ <b>Настройки</b>\n\nПока правил нет. Добавьте первую модель:"
    )
    kb = build_settings_menu(settings)
    if isinstance(target, CallbackQuery):
        await edit_message(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


async def _show_detail(target: Message | CallbackQuery, setting) -> None:
    price = (
        f"{setting.min_price:,.0f}–{setting.max_price:,.0f} BYN"
        if setting.max_price
        else f"от {setting.min_price:,.0f} BYN"
    )
    state = "🟢 активно" if setting.is_active else "🔴 на паузе"
    text = (
        f"📱 <b>{setting.model}</b> (#{setting.id})\n\n"
        f"💰 {price}\n"
        f"📍 {setting.cities}\n"
        f"⏱ {setting.check_interval} сек\n"
        f"🖼 фото: {'вкл' if setting.send_photos else 'выкл'}\n"
        f"📄 описание: {'вкл' if setting.show_description else 'выкл'}\n"
        f"{state}"
    )
    if isinstance(target, CallbackQuery):
        await edit_message(target, text, build_model_detail(setting))
    else:
        await target.answer(text, reply_markup=build_model_detail(setting))


# --- Навигация ---------------------------------------------------------------

@router.callback_query(F.data == "s:add")
async def cb_add(callback: CallbackQuery, db_user, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await edit_message(callback, "Выберите модель:", build_model_browser(0))


@router.callback_query(F.data == "s:back")
async def cb_back(callback: CallbackQuery, db_user, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await show_settings_menu(callback, db_user)


@router.callback_query(F.data == "s:clr")
async def cb_clear_all(callback: CallbackQuery, db_user) -> None:
    n = await clear_settings_for_user(db_user.id)
    await callback.answer(f"⏸️ Остановлено правил: {n}", show_alert=True)
    await show_settings_menu(callback, db_user)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("mb:"))
async def cb_browser_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await edit_message(callback, "Выберите модель:", build_model_browser(page))


@router.callback_query(F.data.startswith("mp:"))
async def cb_pick_model(callback: CallbackQuery, db_user) -> None:
    idx = int(callback.data.split(":")[1])
    models = DEFAULT_LIMIT_MODELS  # тот же список, что в браузере
    if idx >= len(models):
        await callback.answer("Модель не найдена", show_alert=True)
        return
    model = models[idx]

    limits = _limits_for(db_user)
    if limits["max_models"] is not None and await count_settings_for_user(db_user.id) >= limits["max_models"]:
        await callback.answer(
            f"Лимит моделей для «{db_user.access_level}»: {limits['max_models']}",
            show_alert=True,
        )
        return

    default_max = _default_max(model)
    setting = await add_setting(
        db_user.id,
        {
            "model": model,
            "min_price": MIN_PRICE_GLOBAL,
            "max_price": default_max or None,
            "cities": "Минск",
            "check_interval": limits["min_interval"],
        },
    )
    logger.info(f"Правило #{setting.id} создано для {db_user.id}: {model}")
    await callback.answer(f"✅ {model} добавлен")
    await _show_detail(callback, setting)


# --- Редактирование ----------------------------------------------------------

@router.callback_query(F.data.startswith("ed:b:"))
async def cb_open_detail(callback: CallbackQuery, db_user, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    setting = await get_setting(int(callback.data.split(":")[2]))
    if setting is None or setting.user_id != db_user.id:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    await _show_detail(callback, setting)


@router.callback_query(F.data.startswith("ed:t:"))
async def cb_toggle(callback: CallbackQuery, db_user) -> None:
    sid = int(callback.data.split(":")[2])
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    await set_setting_active(sid, not setting.is_active)
    await callback.answer("✅ Готово")
    setting.is_active = not setting.is_active
    await _show_detail(callback, setting)


@router.callback_query(F.data.startswith("ed:d:"))
async def cb_delete(callback: CallbackQuery, db_user) -> None:
    sid = int(callback.data.split(":")[2])
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    await delete_setting(sid)
    await callback.answer(f"🗑 {setting.model} удалён", show_alert=True)
    await show_settings_menu(callback, db_user)


@router.callback_query(F.data.startswith("ed:f:"))
async def cb_toggle_photos(callback: CallbackQuery, db_user) -> None:
    sid = int(callback.data.split(":")[2])
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        return
    await update_setting(sid, send_photos=not setting.send_photos)
    setting.send_photos = not setting.send_photos
    await callback.answer()
    await _show_detail(callback, setting)


@router.callback_query(F.data.startswith("ed:g:"))
async def cb_toggle_desc(callback: CallbackQuery, db_user) -> None:
    sid = int(callback.data.split(":")[2])
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        return
    await update_setting(sid, show_description=not setting.show_description)
    setting.show_description = not setting.show_description
    await callback.answer()
    await _show_detail(callback, setting)


# --- Интервал ----------------------------------------------------------------

@router.callback_query(F.data.startswith("ed:i:"))
async def cb_interval_menu(callback: CallbackQuery, db_user) -> None:
    sid = int(callback.data.split(":")[2])
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        return
    limits = _limits_for(db_user)
    await callback.answer()
    text = (
        f"⏱ <b>{setting.model}</b>\n\n"
        f"Текущий интервал: {setting.check_interval} сек\n"
        f"Минимум для вашего уровня «{db_user.access_level}»: {limits['min_interval']} сек"
    )
    await edit_message(callback, text, build_interval_menu(sid))


@router.callback_query(F.data.startswith("ed:ip:"))
async def cb_interval_preset(callback: CallbackQuery, db_user) -> None:
    _, _, sid, value = callback.data.split(":")
    sid = int(sid)
    interval = int(value)
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        return
    limits = _limits_for(db_user)
    if interval < limits["min_interval"]:
        await callback.answer(
            f"Минимум для «{db_user.access_level}»: {limits['min_interval']} сек",
            show_alert=True,
        )
        return
    await update_setting(sid, check_interval=interval)
    await callback.answer(f"✅ Интервал: {interval} сек")
    setting.check_interval = interval
    await _show_detail(callback, setting)


@router.callback_query(F.data.startswith("ed:ic:"))
async def cb_interval_custom(callback: CallbackQuery, db_user, state: FSMContext) -> None:
    sid = int(callback.data.split(":")[2])
    await state.set_state(IntervalFlow.waiting)
    await state.update_data(setting_id=sid)
    await callback.answer()
    await callback.message.answer(
        "✍️ Введите интервал в <b>секундах</b> (число):\n"
        "Например: <code>120</code> = 2 минуты"
    )


@router.message(IntervalFlow.waiting)
async def on_custom_interval(message: Message, db_user, state: FSMContext) -> None:
    data = await state.get_data()
    sid = int(data["setting_id"])
    try:
        interval = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число в секундах.")
        return
    limits = _limits_for(db_user)
    if interval < limits["min_interval"]:
        await message.answer(f"❌ Минимум для «{db_user.access_level}»: {limits['min_interval']} сек.")
        return
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        await message.answer("Правило не найдено.")
        await state.clear()
        return
    await update_setting(sid, check_interval=interval)
    await state.clear()
    logger.info(f"Интервал {sid} -> {interval} сек для {db_user.id}")
    setting.check_interval = interval
    await message.answer(f"✅ Интервал: {interval} сек")
    await _show_detail(message, setting)


# --- Цена --------------------------------------------------------------------

@router.callback_query(F.data.startswith("ed:p:"))
async def cb_price_start(callback: CallbackQuery, db_user, state: FSMContext) -> None:
    sid = int(callback.data.split(":")[2])
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        return
    await state.set_state(PriceFlow.waiting_min)
    await state.update_data(setting_id=sid)
    await callback.answer()
    await callback.message.answer(
        f"💰 <b>{setting.model}</b>\n\n"
        f"Минимальная цена в BYN:\n"
        f"(минимум {MIN_PRICE_GLOBAL:.0f}, текущая: {setting.min_price:,.0f})"
    )


@router.message(PriceFlow.waiting_min)
async def on_price_min(message: Message, state: FSMContext) -> None:
    try:
        value = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    if value < MIN_PRICE_GLOBAL:
        await message.answer(f"❌ Минимум {MIN_PRICE_GLOBAL:.0f} BYN.")
        return
    await state.update_data(min_price=value)
    await state.set_state(PriceFlow.waiting_max)
    await message.answer("Максимальная цена в BYN (или 0 = без лимита):")


@router.message(PriceFlow.waiting_max)
async def on_price_max(message: Message, db_user, state: FSMContext) -> None:
    data = await state.get_data()
    sid = int(data["setting_id"])
    min_price = float(data["min_price"])
    try:
        raw = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введите число.")
        return

    max_price = raw if raw > 0 else None
    if max_price is not None and max_price < min_price:
        max_price, min_price = min_price, max_price

    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        await message.answer("Правило не найдено.")
        await state.clear()
        return

    await update_setting(sid, min_price=min_price, max_price=max_price)
    await state.clear()
    logger.info(f"Цена {sid} -> {min_price}..{max_price} для {db_user.id}")
    setting.min_price, setting.max_price = min_price, max_price
    await message.answer("✅ Цена обновлена")
    await _show_detail(message, setting)


# --- Города ------------------------------------------------------------------

@router.callback_query(F.data.startswith("ed:c:"))
async def cb_cities_start(callback: CallbackQuery, db_user, state: FSMContext) -> None:
    sid = int(callback.data.split(":")[2])
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        return
    await state.set_state(CitiesFlow.waiting)
    await state.update_data(setting_id=sid)
    await callback.answer()
    await callback.message.answer(
        f"📍 <b>{setting.model}</b>\n\n"
        f"Города через запятую (текущие: {setting.cities}):\n"
        "Например: <code>Минск, Гомель, Брест</code>"
    )


@router.message(CitiesFlow.waiting)
async def on_cities(message: Message, db_user, state: FSMContext) -> None:
    data = await state.get_data()
    sid = int(data["setting_id"])
    cities = ",".join([c.strip() for c in message.text.split(",") if c.strip()])
    if not cities:
        await message.answer("❌ Введите хотя бы один город.")
        return
    setting = await get_setting(sid)
    if setting is None or setting.user_id != db_user.id:
        await message.answer("Правило не найдено.")
        await state.clear()
        return
    await update_setting(sid, cities=cities)
    await state.clear()
    logger.info(f"Города {sid} -> {cities} для {db_user.id}")
    setting.cities = cities
    await message.answer("✅ Города обновлены")
    await _show_detail(message, setting)
