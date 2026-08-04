from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger

from database.db import (
    add_hidden_model,
    get_listing,
    get_setting,
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


@router.callback_query(F.data.startswith("hide:"))
async def cb_hide(callback: CallbackQuery, db_user) -> None:
    model = callback.data.split(":", 1)[1]
    created = await add_hidden_model(db_user.id, model)
    if created:
        logger.info(f"Скрыты похожие «{model}» для {db_user.id}")
        await callback.answer(f"🙈 Похожие на «{model}» скрыты")
    else:
        await callback.answer("Уже скрыто")
