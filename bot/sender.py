from html import escape

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InputMediaPhoto
from loguru import logger

from config import ADMIN_CHAT_ID


def format_listing(listing: dict) -> str:
    title = escape(listing.get("title", "Без названия"))
    price = escape(listing.get("price", "Цена не указана"))
    city = escape(listing.get("city", "Город не указан"))
    battery = listing.get("battery")
    desc = listing.get("description", "").strip()
    url = escape(listing.get("url", "#"))
    is_17 = listing.get("is_17")

    header = f"⭐ <b>{title}</b>" if is_17 else f"📱 <b>{title}</b>"
    parts = [header, f"💰 {price}", f"📍 {city}"]

    user_price = listing.get("user_price")
    if user_price is not None:
        raw = listing.get("price_raw", 0)
        if raw is not None and raw > 0:
            pct = ((user_price - raw) / user_price) * 100
            parts.append(
                f"🎯 Ваша цена: {user_price:,.0f} BYN  |  🔥 <b>-{pct:.0f}%</b>"
            )
        else:
            parts.append(f"🎯 Ваша цена: {user_price:,.0f} BYN")

    if battery:
        parts.append(f"🔋 АКБ: <b>{escape(battery)}</b>")
    if desc:
        parts.append(f"{escape(desc)}")
    parts.append(f"🔗 {url}")

    return "\n".join(parts)


async def send_listing(bot: Bot, chat_id: int, listing: dict) -> bool:
    text = format_listing(listing)
    images = listing.get("images", [])
    try:
        if images:
            try:
                media = [InputMediaPhoto(media=images[0], caption=text, parse_mode=ParseMode.HTML)]
                for url in images[1:]:
                    media.append(InputMediaPhoto(media=url))
                await bot.send_media_group(chat_id=chat_id, media=media[:10])
                logger.info(f"Отправлено объявление {listing.get('id', '?')} в чат {chat_id} ({len(images)} фото)")
                return True
            except Exception:
                logger.warning(f"Не удалось отправить медиа-группу для {listing.get('id', '?')}, отправляю текст+фото")
                try:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=images[0],
                        caption=text,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
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