import json
import os
from typing import Any

from aiohttp import web
from loguru import logger

from config import ACCESS_LIMITS, BOT_TOKEN, DEFAULT_ACCESS_LEVEL, MIN_PRICE_GLOBAL
from database.db import (
    DEFAULT_LIMIT_MODELS,
    add_setting,
    clear_settings_for_user,
    count_settings_for_user,
    get_settings_for_user,
    get_user,
    pause_all_for_user,
    update_setting,
)
from webapp.auth import extract_user, validate_init_data

WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "static")


def _limits_for(level: str) -> dict[str, int]:
    return ACCESS_LIMITS.get(level, ACCESS_LIMITS.get(DEFAULT_ACCESS_LEVEL, ACCESS_LIMITS["free"]))


async def _require_user(request: web.Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    validated = validate_init_data(init_data, BOT_TOKEN)
    user_info = extract_user(validated)
    if user_info is None:
        return None, None
    db_user = await get_user(int(user_info["id"]))
    return db_user, user_info


def _json(data: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _fail(message: str, status: int = 400) -> web.Response:
    return _json({"ok": False, "error": message}, status=status)


def _ok(**kwargs: Any) -> web.Response:
    return _json({"ok": True, **kwargs})


async def _serialize_settings(db_user) -> list[dict[str, Any]]:
    settings = await get_settings_for_user(db_user.id)
    return [
        {
            "id": s.id,
            "model": s.model,
            "min_price": s.min_price,
            "max_price": s.max_price,
            "cities": s.cities,
            "check_interval": s.check_interval,
            "is_active": s.is_active,
            "send_photos": s.send_photos,
            "show_description": s.show_description,
        }
        for s in settings
    ]


# --- Страница ----------------------------------------------------------------

async def index(request: web.Request) -> web.Response:
    html_path = os.path.join(WEBAPP_DIR, "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        return web.Response(text="Mini App not found", status=404)
    return web.Response(text=html, content_type="text/html")


# --- API ---------------------------------------------------------------------

async def api_init(request: web.Request) -> web.Response:
    db_user, user_info = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)
    if db_user.is_blocked or not db_user.is_active:
        return _fail("blocked", 403)
    return _ok(
        user={
            "id": db_user.id,
            "username": db_user.username,
            "first_name": db_user.first_name,
            "access_level": db_user.access_level,
            "is_blocked": db_user.is_blocked,
        },
        limits=_limits_for(db_user.access_level),
    )


async def api_settings(request: web.Request) -> web.Response:
    db_user, _ = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)
    if db_user.is_blocked or not db_user.is_active:
        return _fail("blocked", 403)
    return _ok(
        settings=await _serialize_settings(db_user),
        models=DEFAULT_LIMIT_MODELS,
        limits=_limits_for(db_user.access_level),
        min_price_global=MIN_PRICE_GLOBAL,
    )


async def api_add(request: web.Request) -> web.Response:
    db_user, _ = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)
    if db_user.is_blocked or not db_user.is_active:
        return _fail("blocked", 403)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _fail("bad json")

    model = (body.get("model") or "").strip()
    if model not in DEFAULT_LIMIT_MODELS:
        return _fail(f"Модель не найдена: {model}")

    limits = _limits_for(db_user.access_level)
    if await count_settings_for_user(db_user.id) >= limits["max_models"]:
        return _fail(f"Лимит моделей для «{db_user.access_level}»: {limits['max_models']}")

    try:
        min_price = float(body.get("min_price") or MIN_PRICE_GLOBAL)
        max_price_raw = body.get("max_price")
        max_price = float(max_price_raw) if max_price_raw else None
        check_interval = int(body.get("check_interval") or limits["min_interval"])
    except (TypeError, ValueError):
        return _fail("неверные числа")

    if min_price < MIN_PRICE_GLOBAL:
        return _fail(f"Минимум {MIN_PRICE_GLOBAL:,.0f} BYN")
    if max_price is not None and max_price < min_price:
        max_price, min_price = min_price, max_price
    if check_interval < limits["min_interval"]:
        return _fail(f"Минимум интервал для «{db_user.access_level}»: {limits['min_interval']} сек")

    cities = ",".join([c.strip() for c in (body.get("cities") or "Минск").split(",") if c.strip()]) or "Минск"

    setting = await add_setting(
        db_user.id,
        {
            "model": model,
            "min_price": min_price,
            "max_price": max_price,
            "cities": cities,
            "check_interval": check_interval,
        },
    )
    logger.info(f"[webapp] добавлено правило #{setting.id} для {db_user.id}: {model}")
    return _ok(id=setting.id)


async def api_update(request: web.Request) -> web.Response:
    db_user, _ = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _fail("bad json")

    setting_id = body.get("id")
    if setting_id is None:
        return _fail("id обязателен")

    from database.db import get_setting

    setting = await get_setting(int(setting_id))
    if setting is None or setting.user_id != db_user.id:
        return _fail("правило не найдено", 404)

    limits = _limits_for(db_user.access_level)
    kwargs: dict[str, Any] = {}

    if "min_price" in body or "max_price" in body:
        try:
            min_price = float(body.get("min_price") or setting.min_price or MIN_PRICE_GLOBAL)
            raw_max = body.get("max_price")
            max_price = float(raw_max) if raw_max else setting.max_price
        except (TypeError, ValueError):
            return _fail("неверные числа")
        if min_price < MIN_PRICE_GLOBAL:
            return _fail(f"Минимум {MIN_PRICE_GLOBAL:,.0f} BYN")
        if max_price is not None and max_price < min_price:
            max_price, min_price = min_price, max_price
        kwargs["min_price"] = min_price
        kwargs["max_price"] = max_price

    if "cities" in body:
        cities = ",".join([c.strip() for c in (body.get("cities") or "").split(",") if c.strip()])
        if not cities:
            return _fail("введите города")
        kwargs["cities"] = cities

    if "check_interval" in body:
        try:
            interval = int(body["check_interval"])
        except (TypeError, ValueError):
            return _fail("неверный интервал")
        if interval < limits["min_interval"]:
            return _fail(f"Минимум для «{db_user.access_level}»: {limits['min_interval']} сек")
        kwargs["check_interval"] = interval

    if "send_photos" in body:
        kwargs["send_photos"] = bool(body["send_photos"])
    if "show_description" in body:
        kwargs["show_description"] = bool(body["show_description"])
    if "is_active" in body:
        from database.db import set_setting_active

        await set_setting_active(setting_id, bool(body["is_active"]))
        kwargs.pop("is_active", None)

    if kwargs:
        await update_setting(setting_id, **kwargs)
    logger.info(f"[webapp] обновлено правило #{setting_id} для {db_user.id}")
    return _ok()


async def api_delete(request: web.Request) -> web.Response:
    db_user, _ = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _fail("bad json")

    from database.db import delete_setting, get_setting

    setting = await get_setting(int(body.get("id") or 0))
    if setting is None or setting.user_id != db_user.id:
        return _fail("правило не найдено", 404)
    await delete_setting(setting.id)
    logger.info(f"[webapp] удалено правило #{setting.id} для {db_user.id}")
    return _ok()


async def api_toggle(request: web.Request) -> web.Response:
    db_user, _ = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _fail("bad json")

    from database.db import get_setting, set_setting_active

    setting = await get_setting(int(body.get("id") or 0))
    if setting is None or setting.user_id != db_user.id:
        return _fail("правило не найдено", 404)
    await set_setting_active(setting.id, not setting.is_active)
    return _ok(is_active=not setting.is_active)


async def api_pause_all(request: web.Request) -> web.Response:
    db_user, _ = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)
    n = await pause_all_for_user(db_user.id, paused=True)
    return _ok(updated=n)


async def api_resume_all(request: web.Request) -> web.Response:
    db_user, _ = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)
    n = await pause_all_for_user(db_user.id, paused=False)
    return _ok(updated=n)


async def api_stats(request: web.Request) -> web.Response:
    db_user, _ = await _require_user(request)
    if db_user is None:
        return _fail("unauthorized", 401)

    from database.db import count_notifications_for_user, list_hidden_models

    notified = await count_notifications_for_user(db_user.id)
    hidden = await list_hidden_models(db_user.id)
    settings = await _serialize_settings(db_user)
    return _ok(notified=notified, hidden=hidden, rules_count=len(settings))
