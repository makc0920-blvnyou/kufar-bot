from html import escape

from aiogram import Bot
from aiogram.enums import ParseMode
from loguru import logger

from config import ADMIN_CHAT_ID


def format_listing(listing: dict) -> str:
    title = escape(listing.get("title", "Без названия"))
    price = escape(listing.get("price", "Цена не указана"))
    city = escape(listing.get("city", "Город не указан"))
    battery = listing.get("battery")
    desc = escape(listing.get("description", "").strip())
    url = escape(listing.get("url", "#"))

    parts = [
        f"📱 <b>{title}</b>",
        f"💰 {price}",
        f"📍 {city}",
    ]

    q1 = listing.get("q1")
    median = listing.get("median")
    if q1 is not None and median is not None:
        parts.append(
            f"📊 Рынок: мед {median:,.0f} | Q1 {q1:,.0f} | "
            f"🔥 <b>{listing.get('price_raw', 0):,.0f}</b> ≤ {q1:,.0f}"
        )

    if battery:
        parts.append(f"🔋 АКБ: <b>{escape(battery)}</b>")
    if desc:
        parts.append(f"   {desc}")
    parts.append(f"🔗 {url}")

    return "\n".join(parts)


async def send_listing(bot: Bot, chat_id: int, listing: dict) -> bool:
    text = format_listing(listing)
    image = listing.get("image")
    try:
        if image:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=image,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                )
                logger.info(f"Отправлено объявление {listing.get('id', '?')} в чат {chat_id}")
                return True
            except Exception:
                logger.warning(f"Не удалось отправить фото для {listing.get('id', '?')}, отправляю текст")
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False,
                )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
        logger.info(f"Отправлено объявление {listing.get('id', '?')} в чат {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки объявления {listing.get('id', '?')}: {e}")
        return False


async def send_admin_alert(bot: Bot, message: str) -> None:
    if ADMIN_CHAT_ID is None:
        return

    safe_message = escape(message)
    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"⚠️ <b>Внимание</b>\n{safe_message}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление администратору: {e}")
