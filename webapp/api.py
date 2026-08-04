import json
import os
from typing import Any

from aiohttp import web
from loguru import logger

from config import (
    ADMIN_IDS,
    ACCESS_LIMITS,
    BOT_TOKEN,
    DEFAULT_ACCESS_LEVEL,
    MIN_PRICE_GLOBAL,
    PENDING_LEVEL,
)
from database.db import (
    DEFAULT_LIMIT_MODELS,
    add_setting,
    count_settings_for_user,
    find_user_by_username,
    get_settings_for_user,
    get_user,
    grant_access,
    list_active_users,
    list_favorites,
    list_hidden_models,
    list_users,
    pause_all_for_user,
    remove_favorite,
    remove_hidden_model,
    revoke_access,
    set_access_level,
    update_setting,
)
from database.locations import LOCATIONS
from webapp.auth import extract_user, validate_init_data

WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "static")

# Глобальная ссылка на бота — проставляется из main.py после инициализации.
BOT = None


def set_bot(bot) -> None:
    global BOT
    BOT = bot


def _limits_for(level: str) -> dict[str, int | None]:
    return ACCESS_LIMITS.get(level, ACCESS_LIMITS.get(DEFAULT_ACCESS_LEVEL, ACCESS_LIMITS["free"]))


async def _require_user(request: web.Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    validated = validate_init_data(init_data, BOT_TOKEN)
    user_info = extract_user(validated)
    if user_info is None:
        return None, None
    db_user = await get_user(int(user_info["id"]))
    return db_user, user_info


async def _require_approved(request: web.Request):
    """Требует валидного юзера с доступом (не pending)."""
    db_user, _ = await _require_user(request)
    if db_user is None:
        return None, "unauthorized", 401
    if db_user.is_blocked or not db_user.is_active:
        return None, "blocked", 403
    if db_user.access_level == PENDING_LEVEL:
        return None, "pending", 403
    return db_user, None, None


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
            "is_admin": db_user.id in ADMIN_IDS or db_user.access_level == "admin",
            "premium_expires_at": db_user.premium_expires_at.isoformat()
            if db_user.premium_expires_at
            else None,
        },
        limits=_limits_for(db_user.access_level),
    )


async def api_settings(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)
    return _ok(
        settings=await _serialize_settings(db_user),
        models=DEFAULT_LIMIT_MODELS,
        limits=_limits_for(db_user.access_level),
        min_price_global=MIN_PRICE_GLOBAL,
    )


async def api_locations(request: web.Request) -> web.Response:
    return _ok(locations=LOCATIONS)


async def api_add(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _fail("bad json")

    model = (body.get("model") or "").strip()
    if model not in DEFAULT_LIMIT_MODELS:
        return _fail(f"Модель не найдена: {model}")

    limits = _limits_for(db_user.access_level)
    if limits["max_models"] is not None and await count_settings_for_user(db_user.id) >= limits["max_models"]:
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
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

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
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

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
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _fail("bad json")

    from database.db import (
        count_active_settings_for_user,
        get_setting,
        set_setting_active,
    )

    setting = await get_setting(int(body.get("id") or 0))
    if setting is None or setting.user_id != db_user.id:
        return _fail("правило не найдено", 404)
    if not setting.is_active:
        limits = _limits_for(db_user.access_level)
        if limits["max_models"] is not None:
            active = await count_active_settings_for_user(db_user.id)
            if active >= limits["max_models"]:
                return _fail(
                    f"Лимит активных моделей для «{db_user.access_level}»: "
                    f"{limits['max_models']}. Сначала поставьте на паузу другую."
                )
    await set_setting_active(setting.id, not setting.is_active)
    return _ok(is_active=not setting.is_active)


async def api_pause_all(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)
    n = await pause_all_for_user(db_user.id, paused=True)
    return _ok(updated=n)


async def api_resume_all(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)
    from database.db import resume_settings_limited

    n = await resume_settings_limited(db_user.id, _limits_for(db_user.access_level)["max_models"])
    return _ok(updated=n)


async def api_stats(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

    from services.analytics import build_user_stats

    return _ok(stats=await build_user_stats(db_user))


# --- Избранное ---------------------------------------------------------------

async def api_saved(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

    from database.db import get_listing
    from services.notification import _relative_time

    favorites = await list_favorites(db_user.id)
    items = []
    for fav in favorites:
        listing = await get_listing(fav.listing_id)
        if listing is None:
            continue
        items.append(
            {
                "listing_id": listing.id,
                "title": listing.title,
                "price": listing.price,
                "price_raw": listing.price_raw,
                "city": listing.city,
                "url": listing.url,
                "model": listing.model,
                "storage": listing.storage,
                "images": json.loads(listing.images or "[]"),
                "when": _relative_time(listing.found_at),
            }
        )
    return _ok(saved=items)


async def api_saved_remove(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _fail("bad json")

    removed = await remove_favorite(db_user.id, str(body.get("listing_id") or ""))
    return _ok(removed=removed)


# --- Принудительная проверка --------------------------------------------------

async def api_check(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

    if BOT is None:
        return _fail("бот не готов", 503)

    from scheduler.manager import check_for_user

    sent = await check_for_user(BOT, db_user.id)
    return _ok(sent=sent)


# --- Скрытые модели -----------------------------------------------------------

async def api_hidden(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)
    return _ok(hidden=await list_hidden_models(db_user.id))


async def api_hidden_remove(request: web.Request) -> web.Response:
    db_user, err, code = await _require_approved(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _fail("bad json")

    model = (body.get("model") or "").strip()
    await remove_hidden_model(db_user.id, model)
    return _ok()


# --- Админ -------------------------------------------------------------------

async def _require_admin(request: web.Request):
    db_user, _ = await _require_user(request)
    if db_user is None:
        return None, "unauthorized", 401
    if db_user.is_blocked or not db_user.is_active:
        return None, "blocked", 403
    if db_user.access_level == PENDING_LEVEL:
        return None, "pending", 403
    is_admin = db_user.id in ADMIN_IDS or db_user.access_level == "admin"
    if not is_admin:
        return None, "forbidden", 403
    return db_user, None, None


def _level_label(level: str) -> str:
    return {
        "free": "free",
        "premium": "💎 premium",
        "vip": "👑 vip",
        "admin": "🛠 admin",
        "pending": "⏳ pending",
    }.get(level, level)


async def api_admin_dashboard(request: web.Request) -> web.Response:
    db_user, err, code = await _require_admin(request)
    if err:
        return _fail(err, code)

    from services.analytics import format_admin_dashboard

    users = await list_users()
    active = await list_active_users()
    return _ok(
        users_count=len(users),
        active_count=len(active),
        dashboard=await format_admin_dashboard(),
        admins=ADMIN_IDS,
    )


async def api_admin_users(request: web.Request) -> web.Response:
    db_user, err, code = await _require_admin(request)
    if err:
        return _fail(err, code)

    users = await list_users()
    result = []
    for u in users:
        rules = await get_settings_for_user(u.id)
        result.append(
            {
                "id": u.id,
                "username": u.username,
                "first_name": u.first_name,
                "access_level": u.access_level,
                "level_label": _level_label(u.access_level),
                "is_pending": u.access_level == PENDING_LEVEL,
                "is_active": u.is_active,
                "is_blocked": u.is_blocked,
                "premium_expires_at": u.premium_expires_at.isoformat()
                if u.premium_expires_at
                else None,
                "rules_count": len(rules),
            }
        )
    return _ok(users=result)


async def api_admin_user_level(request: web.Request) -> web.Response:
    db_user, err, code = await _require_admin(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
        target_id = int(body.get("id"))
        level = (body.get("level") or "").strip()
    except (json.JSONDecodeError, TypeError, ValueError):
        return _fail("bad request")

    if level not in ("free", "premium", "vip", "admin"):
        return _fail("уровень: free|premium|vip|admin")
    await set_access_level(target_id, level)
    logger.info(f"[webapp:admin] уровень {target_id} → {level}")
    return _ok()


async def api_admin_user_block(request: web.Request) -> web.Response:
    db_user, err, code = await _require_admin(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
        target_id = int(body.get("id"))
        blocked = bool(body.get("blocked", True))
    except (json.JSONDecodeError, TypeError, ValueError):
        return _fail("bad request")

    if blocked:
        await revoke_access(target_id)
    else:
        await grant_access(target_id, access_level="free")
    logger.info(f"[webapp:admin] {'блокировка' if blocked else 'разблокировка'} {target_id}")
    return _ok()


async def api_admin_user_stats(request: web.Request) -> web.Response:
    db_user, err, code = await _require_admin(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
        target_id = int(body.get("id"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return _fail("bad request")

    from services.analytics import build_user_stats

    target = await get_user(target_id)
    if target is None:
        return _fail("пользователь не найден", 404)
    return _ok(stats=await build_user_stats(target))


async def api_admin_grant(request: web.Request) -> web.Response:
    db_user, err, code = await _require_admin(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
        target = str(body.get("target") or "").strip()
        level = str(body.get("level") or "free").strip()
    except json.JSONDecodeError:
        return _fail("bad json")

    if not target:
        return _fail("укажите @username или user_id")
    if level not in ("free", "premium", "vip"):
        return _fail("уровень: free|premium|vip")

    if target.lstrip("@").isdigit():
        target_id = int(target.lstrip("@"))
    else:
        user = await find_user_by_username(target)
        if user is None:
            return _fail(f"пользователь {target} не найден (сначала /start)")
        target_id = user.id

    user = await grant_access(target_id, access_level=level)
    logger.info(f"[webapp:admin] доступ {target_id} → {level}")

    if BOT is not None:
        try:
            await BOT.send_message(
                target_id,
                f"🎉 Вам выдан доступ к Kufar Monitor! Уровень: {level}\n\n"
                "Добавьте модель через /app или <code>/add_model iPhone 15 600 1200</code>",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить {target_id}: {e}")

    return _ok(id=target_id, level=level)


async def api_admin_broadcast(request: web.Request) -> web.Response:
    db_user, err, code = await _require_admin(request)
    if err:
        return _fail(err, code)

    try:
        body = await request.json()
        text = (body.get("text") or "").strip()
    except json.JSONDecodeError:
        return _fail("bad json")

    if not text:
        return _fail("пустой текст")
    if BOT is None:
        return _fail("бот не готов", 503)

    from services.notification import broadcast

    users = await list_active_users()
    ids = [u.id for u in users]
    if not ids:
        return _ok(sent=0, total=0)
    sent = await broadcast(BOT, ids, text)
    logger.info(f"[webapp:admin] рассылка: {sent}/{len(ids)}")
    return _ok(sent=sent, total=len(ids))
