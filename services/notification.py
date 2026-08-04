from datetime import datetime, timedelta, timezone
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


def _posted_time(found_at: Any) -> str | None:
    """Абсолютное время выкладки объявления (Минск, UTC+3)."""
    dt = None
    if isinstance(found_at, str):
        s = found_at.strip()
        try:
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s[:-1] + "+00:00")
            else:
                dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            dt = None
    elif isinstance(found_at, (int, float)):
        try:
            dt = datetime.fromtimestamp(int(found_at), tz=timezone.utc)
        except (ValueError, OSError):
            dt = None
    if dt is None:
        return None
    minsk = dt.astimezone(timezone(timedelta(hours=3)))
    return minsk.strftime("%d.%m.%Y в %H:%M")


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


def _price_range(setting: UserSettings | None) -> str | None:
    if setting is None:
        return None
    hi = setting.max_price
    if hi:
        return f"{hi:,.0f} BYN"
    lo = setting.min_price
    if lo:
        return f"от {lo:,.0f} BYN"
    return None


def format_listing(listing: dict, setting: UserSettings | None = None) -> str:
    title = escape(listing.get("title", "Без названия"))
    price = escape(listing.get("price", "Цена не указана"))
    city = escape(listing.get("city", "Город не указан"))
    battery = listing.get("battery")
    desc = listing.get("description", "").strip()
    url = escape(listing.get("url", "#"))

    parts: list[str] = []

    # Шапка: модель + бейдж нового + время
    when = _relative_time(listing.get("date"))
    badge = " 🆕" if when == "только что" else ""
    parts.append(f"📱 <b>{title}</b>{badge}")
    meta = [f"📍 {city}"]
    if when:
        meta.append(f"🕒 {when}")
    parts.append(" · ".join(meta))

    posted = _posted_time(listing.get("date"))
    if posted:
        parts.append(f"🕒 Выложено: <b>{posted}</b>")

    # Цена + настроенный лимит
    parts.append("")
    parts.append(f"💰 <b>{price}</b>")
    rng = _price_range(setting)
    if rng:
        parts.append(f"🎯 Ваш лимит: <b>{rng}</b>")

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

    # Характеристики одной строкой
    specs = []
    storage = listing.get("storage", "")
    if storage:
        specs.append(f"💾 {escape(storage)}")
    if battery:
        specs.append(f"🔋 АКБ: <b>{escape(str(battery))}</b>")
    if specs:
        parts.append("")
        parts.append(" · ".join(specs))

    # Телефон (если указан в объявлении)
    phones = listing.get("phones") or []
    if phones:
        from parser.kufar import format_phone

        parts.append(f"📞 <b>{escape(format_phone(phones[0]))}</b>")

    # Описание — всегда, если есть
    if desc:
        parts.append("")
        parts.append("📄 <b>Описание:</b>")
        parts.append(escape(desc[:700]) + ("…" if len(desc) > 700 else ""))

    parts.append("")
    parts.append(f"🔗 <a href=\"{url}\">Открыть на Kufar</a>")
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
