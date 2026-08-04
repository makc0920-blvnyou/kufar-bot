from datetime import datetime, timezone
from html import escape
from typing import Any

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InputMediaPhoto
from loguru import logger

from bot.keyboards.inline import build_listing_keyboard
from config import ADMIN_IDS
from database.models import UserSettings


def _relative_time(found_at: Any) -> str | None:
    """list_time от Куфара — unix-секунды (может быть строка)."""
    try:
        ts = int(str(found_at))
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
    delta = datetime.now(timezone.utc) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "только что"
    if seconds < 3600:
        return f"{seconds // 60} мин назад"
    if seconds < 86400:
        return f"{seconds // 3600} ч назад"
    return f"{seconds // 86400} дн назад"


def _find_model_limit(title: str, model: str) -> float | None:
    from database.db import MODEL_PRICES

    mp = MODEL_PRICES.get(model)
    if mp is not None:
        return float(mp)
    keys = sorted(MODEL_PRICES, key=len, reverse=True)
    for key in keys:
        if key.lower() in title.lower():
            return float(MODEL_PRICES[key])
    return None


def format_listing(listing: dict, setting: UserSettings | None = None) -> str:
    title = escape(listing.get("title", "Без названия"))
    price = escape(listing.get("price", "Цена не указана"))
    city = escape(listing.get("city", "Город не указан"))
    battery = listing.get("battery")
    desc = listing.get("description", "").strip()
    url = escape(listing.get("url", "#"))

    parts: list[str] = []

    # НОВОЕ + относительное время
    when = _relative_time(listing.get("date"))
    badge = "🆕 <b>НОВОЕ</b> " if when == "только что" else ""
    parts.append(f"📱 {badge}<b>{title}</b>")
    if when:
        parts.append(f"🕒 {when}")

    parts.append(f"💰 {price}")
    parts.append(f"📍 {city}")

    raw = listing.get("price_raw")
    limit = setting.max_price if setting is not None else None
    if raw is not None and raw > 0:
        if limit:
            diff = ((limit - raw) / limit) * 100
            if diff >= 20:
                parts.append(f"🔥 <b>Сделка! −{diff:.0f}% от вашего лимита</b>")
        else:
            model_limit = _find_model_limit(listing.get("title", ""), listing.get("model", ""))
            if model_limit and raw < model_limit:
                diff = ((model_limit - raw) / model_limit) * 100
                parts.append(f"🎯 Ниже рынка на <b>{diff:.0f}%</b>")

    if battery:
        parts.append(f"🔋 АКБ: <b>{escape(str(battery))}</b>")

    if setting is None or setting.show_description:
        if desc:
            parts.append(f"{escape(desc[:500])}")

    if setting is not None:
        storage = listing.get("storage", "")
        if storage:
            parts.append(f"💾 {escape(storage)}")

    parts.append(f"🔗 {url}")
    return "\n".join(parts)


async def send_listing_to_user(
    bot: Bot,
    user_id: int,
    setting: UserSettings,
    listing: dict,
) -> bool:
    text = format_listing(listing, setting)
    images = listing.get("images", [])
    kb = build_listing_keyboard(listing, setting.id)

    if setting.send_photos and images:
        try:
            media = [InputMediaPhoto(media=images[0], caption=text, parse_mode=ParseMode.HTML)]
            for url in images[1:]:
                media.append(InputMediaPhoto(media=url))
            await bot.send_media_group(chat_id=user_id, media=media[:10])
            return True
        except Exception as e:
            logger.debug(f"Медиа-группа не прошла ({listing.get('id', '?')}): {e}")

    try:
        if images:
            await bot.send_photo(
                chat_id=user_id,
                photo=images[0],
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки объявления {listing.get('id', '?')} юзеру {user_id}: {e}")
        return False


async def send_admin_alert(bot: Bot, message: str) -> None:
    safe_message = escape(message)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ <b>Внимание</b>\n{safe_message}",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Не удалось отправить алерт админу {admin_id}: {e}")


async def broadcast(bot: Bot, user_ids: list[int], text: str) -> int:
    sent = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception as e:
            logger.warning(f"Broadcast не доставлен {uid}: {e}")
    return sent


async def edit_message(target, text: str, kb=None) -> None:
    """Правка сообщения для CallbackQuery или ответ для Message."""
    try:
        if hasattr(target, "message") and target.message is not None:
            await target.message.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        else:
            await target.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.warning(f"edit_text не прошёл: {e}")
        try:
            await target.answer(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        except Exception as e2:
            logger.error(f"Не удалось показать сообщение: {e2}")
