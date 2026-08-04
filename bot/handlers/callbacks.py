from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger

from bot.keyboards.inline import build_settings_menu
from database.db import (
    get_listing,
    get_setting,
    pause_all_for_user,
    save_favorite,
    set_setting_active,
)

router = Router()


@router.callback_query(F.data.startswith("save:"))
async def cb_save(callback: CallbackQuery, db_user) -> None:
    listing_id = callback.data.split(":", 1)[1]
    listing = await get_listing(listing_id)
    if listing is None:
        await callback.answer("Объявление недоступно в БД.", show_alert=True)
        return
    created = await save_favorite(db_user.id, listing_id)
    if created:
        await callback.answer("⭐ Добавлено в избранное")
    else:
        await callback.answer("Уже в избранном")


@router.callback_query(F.data.startswith("pause:"))
async def cb_pause(callback: CallbackQuery, db_user) -> None:
    setting_id = int(callback.data.split(":", 1)[1])
    setting = await get_setting(setting_id)
    if setting is None or setting.user_id != db_user.id:
        await callback.answer("Правило не найдено.", show_alert=True)
        return
    await set_setting_active(setting_id, False)
    logger.info(f"Пауза правила #{setting_id} для {db_user.id}")
    await callback.answer(f"⏸️ {setting.model} — пауза включена")


@router.callback_query(F.data == "settings:add_model")
async def cb_settings_add_model(callback: CallbackQuery, db_user) -> None:
    await callback.answer()
    await callback.message.answer(
        "➕ <b>Добавить модель</b>\n\n"
        "<code>/add_model Модель [мин] [макс] [интервал_сек] [города]</code>\n\n"
        "Пример:\n<code>/add_model iPhone 15 Pro 700 1400 300 Минск,Гомель</code>"
    )


@router.callback_query(F.data == "settings:list_models")
async def cb_settings_list_models(callback: CallbackQuery, db_user) -> None:
    await callback.answer()
    from bot.handlers.user import cmd_my_models

    await cmd_my_models(callback.message, db_user)


@router.callback_query(F.data == "settings:pause_all")
async def cb_settings_pause_all(callback: CallbackQuery, db_user) -> None:
    n = await pause_all_for_user(db_user.id, paused=True)
    await callback.answer(f"⏸️ Пауза включена ({n} правил)", show_alert=True)


@router.callback_query(F.data == "settings:resume_all")
async def cb_settings_resume_all(callback: CallbackQuery, db_user) -> None:
    n = await pause_all_for_user(db_user.id, paused=False)
    await callback.answer(f"▶️ Возобновлено ({n} правил)", show_alert=True)
