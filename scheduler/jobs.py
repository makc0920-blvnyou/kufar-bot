import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any

from aiogram import Bot
from loguru import logger

from config import ALL_CHAT_IDS, CHECK_INTERVAL_MINUTES
from database.db import is_listing_exists, save_listing, get_total_listings, get_recent_prices_for_group, calc_quartiles
from parser.kufar import fetch_listings
from bot.sender import send_listing, format_listing

MIN_SAMPLE = 5
PRICE_WINDOW_HOURS = 12

_lock = asyncio.Lock()

_check_count: int = 0
_total_found: int = 0
_last_check_time: datetime | None = None
_scheduler_running: bool = False


def get_stats() -> dict[str, Any]:
    return {
        "check_count": _check_count,
        "total_found": _total_found,
        "last_check": (
            _last_check_time.strftime("%Y-%m-%d %H:%M:%S")
            if _last_check_time
            else None
        ),
        "is_running": _lock.locked(),
        "interval": CHECK_INTERVAL_MINUTES,
        "scheduler_running": _scheduler_running,
    }


def set_scheduler_status(running: bool) -> None:
    global _scheduler_running
    _scheduler_running = running


async def check_kufar(bot: Bot) -> str:
    global _check_count, _total_found, _last_check_time

    if _lock.locked():
        logger.warning("Предыдущая проверка ещё не завершена, пропускаем")
        return "⏳ Предыдущая проверка ещё выполняется, попробуйте позже"

    async with _lock:
        _check_count += 1
        logger.info(f"Запуск проверки #{_check_count}")

        listings = await fetch_listings()
        if not listings:
            msg = f"Проверка #{_check_count}: не удалось получить объявления"
            logger.info(msg)
            _last_check_time = datetime.now()
            return msg

        new_count = 0
        for listing in listings:
            listing_id = listing.get("id", "")
            if not listing_id:
                continue

            if await is_listing_exists(listing_id):
                continue

            model = listing.get("model", "")
            storage = listing.get("storage", "")

            now_iso = datetime.now().isoformat()

            await save_listing(
                listing_id=listing_id,
                title=listing.get("title", ""),
                price=listing.get("price", ""),
                city=listing.get("city", ""),
                url=listing.get("url", ""),
                description=listing.get("description", ""),
                found_at=listing.get("date", ""),
                model=model,
                storage=storage,
                price_raw=listing.get("price_raw"),
                fetched_at=now_iso,
            )

            listing_price = listing.get("price_raw")
            is_deal = False

            if model and storage and listing_price is not None:
                prices = await get_recent_prices_for_group(model, storage, hours=PRICE_WINDOW_HOURS)
                if len(prices) >= MIN_SAMPLE:
                    q1, q2, q3 = calc_quartiles(prices)
                    listing["median"] = q2
                    listing["q1"] = q1
                    listing["q3"] = q3
                    listing["price_diff"] = round(listing_price - q2, 2)

                    if listing_price <= q1:
                        is_deal = True
                    else:
                        logger.info(
                            f"Пропущено ({listing_price:.2f} > Q1 {q1:.2f}): "
                            f"{listing.get('title','')} — {listing.get('price','')}"
                        )
                        continue
                else:
                    logger.info(
                        f"Мало данных ({len(prices)} < {MIN_SAMPLE}) для {model} {storage}, "
                        f"пропускаем фильтр и отправляем"
                    )
                    is_deal = True
            else:
                is_deal = True

            if not is_deal:
                continue

            sent_any = False
            for cid in ALL_CHAT_IDS:
                if await send_listing(bot, cid, listing):
                    sent_any = True
            if sent_any:
                _total_found += 1
                new_count += 1

        _last_check_time = datetime.now()

        msg = f"Проверка #{_check_count}: найдено {new_count} новых объявлений"
        logger.info(msg)

        if new_count == 0:
            total_in_db = await get_total_listings()
            logger.debug(f"Всего объявлений в БД: {total_in_db}")

        return msg


async def analyze_prices(bot: Bot) -> str:
    logger.info("Запуск дневного анализа цен")

    listings = await fetch_listings(max_items=100)
    if not listings:
        msg = "Анализ цен: не удалось получить объявления"
        logger.warning(msg)
        return msg

    groups: dict[str, dict[str, list[float]]] = {}
    for item in listings:
        model = item.get("model", "")
        storage = item.get("storage", "")
        price = item.get("price_raw")
        if not model or not storage or price is None:
            continue
        groups.setdefault(model, {}).setdefault(storage, []).append(price)

    if not groups:
        msg = "Анализ цен: нет данных для анализа"
        logger.info(msg)
        return msg

    lines: list[str] = [
        "📊 <b>Анализ рынка iPhone</b>",
        f"🏙 Минск | {datetime.now().strftime('%d.%m.%Y')}",
        f"⚡ Сделка: цена ≤ Q1 (25% самых дешёвых)",
        "",
    ]

    for model in sorted(groups):
        lines.append(f"<b>{model}</b>")
        for storage in sorted(groups[model]):
            prices = sorted(groups[model][storage])
            q1, q2, q3 = calc_quartiles(prices)
            lines.append(
                f"  <b>{storage}</b> — {len(prices)} шт. | "
                f"мин {min(prices):,.0f} | "
                f"Q1 {q1:,.0f} | "
                f"мед {q2:,.0f} | "
                f"Q3 {q3:,.0f} | "
                f"макс {max(prices):,.0f}"
            )
            lines.append(f"    🔥 сделка ≤ <b>{q1:,.0f}</b> BYN")
        lines.append("")

    text = "\n".join(lines)

    for cid in ALL_CHAT_IDS:
        try:
            await bot.send_message(
                chat_id=cid,
                text=text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Ошибка отправки анализа цен в чат {cid}: {e}")

    logger.info(f"Анализ цен отправлен: {len(groups)} моделей")
    return f"Анализ цен: {len(groups)} моделей"
