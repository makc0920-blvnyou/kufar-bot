import asyncio
import time
from typing import Any

from aiogram import Bot
from loguru import logger

from config import (
    DEFAULT_CHECK_INTERVAL_SECONDS,
    KUFAR_CACHE_TTL_SECONDS,
    MIN_PRICE_GLOBAL,
)
from database.db import (
    get_active_settings,
    is_model_hidden,
    listing_exists,
    notification_exists,
    record_notification,
    save_listing,
)
from database.locations import REGION_NAMES
from parser.kufar import fetch_listings
from services.notification import send_listing_to_user

_lock = asyncio.Lock()

_fetch_cache: list[dict[str, Any]] | None = None
_fetch_cache_time: float = 0.0

_last_run_by_setting: dict[int, float] = {}


async def _cached_fetch() -> list[dict[str, Any]]:
    """Фетчим список объявлений с кэшем, чтобы не дёргать Куфар на каждый тик."""
    global _fetch_cache, _fetch_cache_time
    now = time.monotonic()
    if _fetch_cache is not None and (now - _fetch_cache_time) < KUFAR_CACHE_TTL_SECONDS:
        return _fetch_cache
    listings = await fetch_listings()
    _fetch_cache = listings
    _fetch_cache_time = now
    return listings


def _city_matches(city_str: str, selected: list[str]) -> bool:
    """Точный матчинг города/района/региона.

    city_str от Куфара вида «Минск», «Минск, Ленинский», «Брестская область, Брест».
    Токен «Брест» не должен матчить «Брестская область, Барановичи».
    """
    parts = [p.strip() for p in city_str.split(",")]
    region = parts[0] if parts else ""
    area = parts[1] if len(parts) > 1 else ""

    for c in selected:
        if not c:
            continue
        c = c.strip()
        if c == region or (area and c == area):
            return True
        if c in REGION_NAMES:
            continue  # выбран другой регион
        # случай, когда город = только регион (напр. «Минск»), а выбор = часть области
        if not area and c in region:
            return True
    return False


def match_setting(listing: dict[str, Any], setting) -> bool:
    price = listing.get("price_raw")
    if price is None:
        return False
    if price < MIN_PRICE_GLOBAL:
        return False

    if setting.min_price is not None and price < setting.min_price:
        return False
    if setting.max_price is not None and price > setting.max_price:
        return False

    model = (listing.get("model") or "").lower()
    title = (listing.get("title") or "").lower()
    target = (setting.model or "").lower()
    if target and target not in model and target not in title:
        return False

    cities = [c.strip() for c in (setting.cities or "").split(",") if c.strip()]
    if cities:
        if not _city_matches((listing.get("city") or "").strip(), cities):
            return False

    return True


async def check_for_user(bot: Bot, user_id: int) -> int:
    """Принудительная проверка для одного пользователя (команда /check)."""
    from database.db import get_settings_for_user

    settings = await get_settings_for_user(user_id)
    if not settings:
        return 0

    listings = await _cached_fetch()
    if not listings:
        return 0

    sent_count = 0
    for setting in settings:
        if not setting.is_active:
            continue
        for listing in listings:
            lid = listing.get("id", "")
            if not lid:
                continue
            if await notification_exists(user_id, lid):
                continue
            if await is_model_hidden(user_id, listing.get("model", "")):
                continue
            if not match_setting(listing, setting):
                continue
            ok = await send_listing_to_user(bot, user_id, setting, listing)
            if ok:
                await record_notification(user_id, lid)
                sent_count += 1
    return sent_count


async def check_all_users(bot: Bot) -> int:
    """Один проход: проверяем каждое активное правило с учётом его интервала."""
    if _lock.locked():
        return 0

    async with _lock:
        now = time.monotonic()
        settings = await get_active_settings()
        if not settings:
            return 0

        listings = await _cached_fetch()
        if not listings:
            return 0

        # Сначала сохраняем новые объявления глобально (дедуп + избранное)
        for listing in listings:
            lid = listing.get("id", "")
            if lid and not await listing_exists(lid):
                await save_listing(listing)

        sent_count = 0
        for setting in settings:
            interval = setting.check_interval or DEFAULT_CHECK_INTERVAL_SECONDS
            last = _last_run_by_setting.get(setting.id, 0.0)
            if now - last < interval:
                continue
            _last_run_by_setting[setting.id] = now

            for listing in listings:
                lid = listing.get("id", "")
                if not lid:
                    continue
                if await notification_exists(setting.user_id, lid):
                    continue
                if await is_model_hidden(setting.user_id, listing.get("model", "")):
                    continue
                if not match_setting(listing, setting):
                    continue
                ok = await send_listing_to_user(bot, setting.user_id, setting, listing)
                if ok:
                    await record_notification(setting.user_id, lid)
                    sent_count += 1

        if sent_count:
            logger.info(f"Проверка: отправлено {sent_count} уведомлений")
        return sent_count
