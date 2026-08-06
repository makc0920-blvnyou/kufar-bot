import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import ACCESS_LIMITS, DATABASE_URL, PENDING_LEVEL, PREMIUM_DURATION_DAYS
from database.models import (
    AppMeta,
    Base,
    HiddenModel,
    Listing,
    Notification,
    SavedListing,
    User,
    UserSettings,
)

MODEL_PRICES: dict[str, int] = {
    "iPhone X": 150,
    "iPhone XR": 200,
    "iPhone XS": 200,
    "iPhone XS Max": 210,
    "iPhone 11": 220,
    "iPhone 11 Pro": 280,
    "iPhone 11 Pro Max": 300,
    "iPhone SE (2-го поколения)": 170,
    "iPhone 12": 300,
    "iPhone 12 mini": 300,
    "iPhone 12 Pro": 520,
    "iPhone 12 Pro Max": 520,
    "iPhone 13": 550,
    "iPhone 13 mini": 550,
    "iPhone 13 Pro": 700,
    "iPhone 13 Pro Max": 700,
    "iPhone SE (3-го поколения)": 250,
    "iPhone 14": 700,
    "iPhone 14 Plus": 700,
    "iPhone 14 Pro": 1000,
    "iPhone 14 Pro Max": 1000,
    "iPhone 15": 1000,
    "iPhone 15 Plus": 1000,
    "iPhone 15 Pro": 1460,
    "iPhone 15 Pro Max": 1460,
    "iPhone 16": 1500,
    "iPhone 16 Plus": 1500,
    "iPhone 16 Pro": 2000,
    "iPhone 16 Pro Max": 2000,
    "iPhone 16e": 1500,
    "iPhone 17": 1950,
    "iPhone 17 Pro": 1950,
    "iPhone 17 Pro Max": 1950,
    "iPhone Air": 1950,
    "iPhone 17e": 1950,
}

DEFAULT_LIMIT_MODELS: list[str] = sorted(MODEL_PRICES.keys())


def _normalize_db_url(url: str) -> str:
    """Neon отдаёт postgresql:// с sslmode — переводим на asyncpg (SSL через connect_args)."""
    if url.startswith("postgresql://"):
        if "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if "?sslmode=require" in url:
            url = url.replace("?sslmode=require", "")
        elif "&sslmode=require" in url:
            url = url.replace("&sslmode=require", "")
    return url


engine = create_async_engine(
    _normalize_db_url(DATABASE_URL),
    echo=False,
    pool_pre_ping=True,
    connect_args={"ssl": "require"} if DATABASE_URL.startswith("postgresql://") else {},
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Лёгкая миграция: новая колонка в существующей таблице
    is_pg = engine.dialect.name == "postgresql"
    if is_pg:
        ddl = "ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_expires_at TIMESTAMP WITH TIME ZONE"
    else:
        ddl = "ALTER TABLE users ADD COLUMN premium_expires_at DATETIME"
    try:
        async with engine.begin() as conn:
            await conn.execute(text(ddl))
    except Exception as e:
        logger.warning(f"Миграция premium_expires_at не прошла (или колонка уже есть): {e}")
    logger.info(f"БД инициализирована: {_normalize_db_url(DATABASE_URL)}")


# --- Пользователи ------------------------------------------------------------

async def get_user(user_id: int) -> Optional[User]:
    async with SessionLocal() as session:
        return await session.get(User, user_id)


async def ensure_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    access_level: str = PENDING_LEVEL,
    is_admin: bool = False,
) -> User:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                username=username,
                first_name=first_name,
                access_level="admin" if is_admin else access_level,
            )
            session.add(user)
        else:
            if username is not None:
                user.username = username
            if first_name is not None:
                user.first_name = first_name
        await session.commit()
        await session.refresh(user)
        return user


def _apply_premium_expiry(user: User, level: str) -> None:
    if level == "premium":
        user.premium_expires_at = datetime.now(timezone.utc) + timedelta(days=PREMIUM_DURATION_DAYS)
    else:
        user.premium_expires_at = None


async def grant_access(user_id: int, access_level: str = "free") -> User:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = User(id=user_id, access_level=access_level)
            session.add(user)
        else:
            user.is_blocked = False
            user.is_active = True
            user.access_level = access_level
        _apply_premium_expiry(user, access_level)
        await session.commit()
        await session.refresh(user)
        if access_level == "free":
            await pause_settings_over_limit(user_id, ACCESS_LIMITS["free"]["max_models"])
        return user


async def revoke_access(user_id: int) -> None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.is_blocked = True
            user.is_active = False
            user.premium_expires_at = None
            await session.commit()


async def set_access_level(user_id: int, level: str) -> None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.access_level = level
            _apply_premium_expiry(user, level)
            await session.commit()
    if level == "free":
        await pause_settings_over_limit(user_id, ACCESS_LIMITS["free"]["max_models"])


async def list_pending_users() -> list[User]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.access_level == PENDING_LEVEL).order_by(User.created_at.desc())
        )
        return list(result.scalars().all())


async def downgrade_expired_premiums() -> int:
    """Возвращает счётчик юзеров, чей premium истёк (→ free)."""
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(
                User.access_level == "premium",
                User.premium_expires_at.is_not(None),
                User.premium_expires_at < now,
            )
        )
        expired = list(result.scalars().all())
        for user in expired:
            user.access_level = "free"
            user.premium_expires_at = None
        if expired:
            await session.commit()
            logger.info(f"Premium истёк, даунгрейд до free: {[u.id for u in expired]}")
        else:
            return 0
    for user in expired:
        await pause_settings_over_limit(user.id, ACCESS_LIMITS["free"]["max_models"])
    return len(expired)


async def count_active_settings_for_user(user_id: int) -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.count()).select_from(UserSettings).where(
                UserSettings.user_id == user_id, UserSettings.is_active.is_(True)
            )
        )
        return int(result.scalar() or 0)


async def pause_settings_over_limit(user_id: int, max_active: int) -> int:
    """Оставляет max_active самых старых активных, остальные уводит в паузу."""
    if not max_active:
        return 0
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserSettings)
            .where(UserSettings.user_id == user_id, UserSettings.is_active.is_(True))
            .order_by(UserSettings.id)
        )
        actives = list(result.scalars().all())
        extra = actives[max_active:]
        for s in extra:
            s.is_active = False
        if extra:
            await session.commit()
            logger.info(f"Пользователь {user_id}: {len(extra)} моделей сверх лимита {max_active} уведены в паузу")
        return len(extra)


async def resume_settings_limited(user_id: int, max_active: int | None) -> int:
    """Активирует приостановленные настройки, пока активно не станет больше max_active."""
    if max_active is None:
        return await pause_all_for_user(user_id, paused=False)
    async with SessionLocal() as session:
        active_count = (
            await session.execute(
                select(func.count()).select_from(UserSettings).where(
                    UserSettings.user_id == user_id, UserSettings.is_active.is_(True)
                )
            )
        ).scalar_one()
        need = int(max_active) - int(active_count or 0)
        if need <= 0:
            return 0
        result = await session.execute(
            select(UserSettings)
            .where(UserSettings.user_id == user_id, UserSettings.is_active.is_(False))
            .order_by(UserSettings.id)
            .limit(need)
        )
        paused = list(result.scalars().all())
        for s in paused:
            s.is_active = True
        if paused:
            await session.commit()
        return len(paused)


async def find_user_by_username(username: str) -> Optional[User]:
    username = username.lstrip("@").strip().lower()
    if not username:
        return None
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username.ilike(username)))
        return result.scalar_one_or_none()


async def list_users() -> list[User]:
    async with SessionLocal() as session:
        result = await session.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())


async def list_active_users() -> list[User]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.is_active == True, User.is_blocked == False)
        )
        return list(result.scalars().all())


# --- Настройки ---------------------------------------------------------------

async def add_setting(user_id: int, data: dict[str, Any]) -> UserSettings:
    async with SessionLocal() as session:
        setting = UserSettings(user_id=user_id, **data)
        session.add(setting)
        await session.commit()
        await session.refresh(setting)
        return setting


async def get_settings_for_user(user_id: int) -> list[UserSettings]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserSettings)
            .where(UserSettings.user_id == user_id)
            .order_by(UserSettings.id.desc())
        )
        return list(result.scalars().all())


async def get_active_settings() -> list[UserSettings]:
    """Все активные правила активных пользователей."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserSettings)
            .join(User, UserSettings.user_id == User.id)
            .where(
                UserSettings.is_active == True,
                User.is_active == True,
                User.is_blocked == False,
            )
        )
        return list(result.scalars().all())


async def get_setting(setting_id: int) -> Optional[UserSettings]:
    async with SessionLocal() as session:
        return await session.get(UserSettings, setting_id)


async def set_setting_active(setting_id: int, active: bool) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(UserSettings)
            .where(UserSettings.id == setting_id)
            .values(is_active=active)
        )
        await session.commit()


async def delete_setting(setting_id: int) -> None:
    async with SessionLocal() as session:
        setting = await session.get(UserSettings, setting_id)
        if setting is not None:
            await session.delete(setting)
            await session.commit()


async def pause_all_for_user(user_id: int, paused: bool) -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            update(UserSettings)
            .where(UserSettings.user_id == user_id)
            .values(is_active=not paused)
        )
        await session.commit()
        return result.rowcount or 0


async def count_settings_for_user(user_id: int) -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        return len(result.scalars().all())


async def update_setting(
    setting_id: int,
    *,
    min_price: float | None = None,
    max_price: float | None = None,
    cities: str | None = None,
    check_interval: int | None = None,
    send_photos: bool | None = None,
    show_description: bool | None = None,
) -> bool:
    values: dict[str, Any] = {}
    if min_price is not None:
        values["min_price"] = min_price
    if max_price is not None:
        values["max_price"] = max_price
    if cities is not None:
        values["cities"] = cities
    if check_interval is not None:
        values["check_interval"] = check_interval
    if send_photos is not None:
        values["send_photos"] = send_photos
    if show_description is not None:
        values["show_description"] = show_description
    if not values:
        return False

    async with SessionLocal() as session:
        result = await session.execute(
            update(UserSettings).where(UserSettings.id == setting_id).values(**values)
        )
        await session.commit()
        return (result.rowcount or 0) > 0


async def clear_settings_for_user(user_id: int) -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            update(UserSettings).where(UserSettings.user_id == user_id).values(is_active=False)
        )
        await session.commit()
        return result.rowcount or 0


# --- Скрытые модели ----------------------------------------------------------

async def add_hidden_model(user_id: int, model: str) -> bool:
    model = (model or "").strip()
    if not model:
        return False
    async with SessionLocal() as session:
        exists = await session.execute(
            select(HiddenModel).where(
                HiddenModel.user_id == user_id,
                HiddenModel.model == model,
            )
        )
        if exists.scalar_one_or_none() is not None:
            return False
        session.add(HiddenModel(user_id=user_id, model=model))
        await session.commit()
        return True


async def is_model_hidden(user_id: int, model: str) -> bool:
    if not model:
        return False
    async with SessionLocal() as session:
        result = await session.execute(
            select(HiddenModel.id).where(
                HiddenModel.user_id == user_id,
                HiddenModel.model == model,
            )
        )
        return result.scalar_one_or_none() is not None


async def list_hidden_models(user_id: int) -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(HiddenModel).where(HiddenModel.user_id == user_id)
        )
        return [h.model for h in result.scalars().all()]


async def remove_hidden_model(user_id: int, model: str) -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(HiddenModel).where(
                HiddenModel.user_id == user_id,
                HiddenModel.model == model,
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            await session.commit()


# --- Объявления --------------------------------------------------------------

async def listing_exists(listing_id: str) -> bool:
    async with SessionLocal() as session:
        return await session.get(Listing, listing_id) is not None


async def save_listing(listing: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        existing = await session.get(Listing, listing.get("id", ""))
        if existing is not None:
            return
        row = Listing(
            id=listing.get("id", ""),
            title=listing.get("title", ""),
            price=listing.get("price", ""),
            price_raw=listing.get("price_raw"),
            city=listing.get("city", ""),
            url=listing.get("url", ""),
            description=listing.get("description", ""),
            model=listing.get("model", ""),
            storage=listing.get("storage", ""),
            images=json.dumps(listing.get("images", []), ensure_ascii=False),
            found_at=listing.get("date", ""),
            fetched_at=datetime.now().isoformat(),
        )
        session.add(row)
        await session.commit()


async def get_listing(listing_id: str) -> Optional[Listing]:
    async with SessionLocal() as session:
        return await session.get(Listing, listing_id)


async def sync_listing(listing: dict[str, Any]) -> bool:
    """Сохранить объявление или обновить цену при её изменении.

    Возвращает True, если объявление новое. Одна SELECT-операция на элемент;
    UPDATE выполняется только при реальном изменении цены.
    """
    lid = listing.get("id", "")
    async with SessionLocal() as session:
        existing = await session.get(Listing, lid)
        if existing is None:
            row = Listing(
                id=lid,
                title=listing.get("title", ""),
                price=listing.get("price", ""),
                price_raw=listing.get("price_raw"),
                city=listing.get("city", ""),
                url=listing.get("url", ""),
                description=listing.get("description", ""),
                model=listing.get("model", ""),
                storage=listing.get("storage", ""),
                images=json.dumps(listing.get("images", []), ensure_ascii=False),
                found_at=listing.get("date", ""),
                fetched_at=datetime.now().isoformat(),
            )
            session.add(row)
            await session.commit()
            return True
        new_price_raw = listing.get("price_raw")
        if existing.price_raw != new_price_raw:
            existing.price = listing.get("price", "")
            existing.price_raw = new_price_raw
            existing.fetched_at = datetime.now().isoformat()
            await session.commit()
        return False


async def get_recent_price_raw(model: str, hours: int = 12) -> list[float]:
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    async with SessionLocal() as session:
        result = await session.execute(
            select(Listing.price_raw)
            .where(
                Listing.model == model,
                Listing.price_raw.is_not(None),
                Listing.fetched_at >= cutoff,
            )
            .order_by(Listing.price_raw)
        )
        return [r for r in result.scalars().all() if r is not None]


async def count_listings() -> int:
    from sqlalchemy import func

    async with SessionLocal() as session:
        result = await session.execute(select(func.count(Listing.id)))
        return int(result.scalar() or 0)


# --- Избранное ---------------------------------------------------------------

async def save_favorite(user_id: int, listing_id: str) -> bool:
    async with SessionLocal() as session:
        exists = await session.execute(
            select(SavedListing).where(
                SavedListing.user_id == user_id,
                SavedListing.listing_id == listing_id,
            )
        )
        if exists.scalar_one_or_none() is not None:
            return False
        session.add(SavedListing(user_id=user_id, listing_id=listing_id))
        await session.commit()
        return True


async def list_favorites(user_id: int) -> list[SavedListing]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(SavedListing)
            .where(SavedListing.user_id == user_id)
            .order_by(SavedListing.saved_at.desc())
        )
        return list(result.scalars().all())


async def remove_favorite(user_id: int, listing_id: str) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(
            select(SavedListing).where(
                SavedListing.user_id == user_id,
                SavedListing.listing_id == listing_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


# --- Уведомления -------------------------------------------------------------

async def notification_exists(user_id: int, listing_id: str) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.listing_id == listing_id,
            )
        )
        return result.scalar_one_or_none() is not None


async def load_notification_map() -> dict[int, set[str]]:
    """user_id -> множество listing_id (уже отправленных). Для матчинга в памяти."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(Notification.user_id, Notification.listing_id)
        )
    out: dict[int, set[str]] = {}
    for uid, lid in result.all():
        out.setdefault(uid, set()).add(lid)
    return out


async def load_hidden_map() -> dict[int, set[str]]:
    """user_id -> множество скрытых моделей. Для матчинга в памяти."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(HiddenModel.user_id, HiddenModel.model)
        )
    out: dict[int, set[str]] = {}
    for uid, model in result.all():
        out.setdefault(uid, set()).add(model)
    return out


async def record_notification(user_id: int, listing_id: str) -> None:
    """Записывает факт отправки (дедуп). Игнорирует дубли (гонки/несколько правил).

    Атомарный upsert: если строка уже есть — ничего не делаем и не роняем тик.
    """
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(Notification)
            .values(user_id=user_id, listing_id=listing_id)
            .on_conflict_do_nothing(
                index_elements=["user_id", "listing_id"]
            )
        )
        async with SessionLocal() as session:
            await session.execute(stmt)
            await session.commit()
        return
    try:
        async with SessionLocal() as session:
            session.add(Notification(user_id=user_id, listing_id=listing_id))
            await session.commit()
    except Exception:
        async with SessionLocal() as session:
            await session.rollback()


async def count_notifications_for_user(user_id: int) -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Notification).where(Notification.user_id == user_id)
        )
        return len(result.scalars().all())


async def notifications_since(user_id: int, days: int) -> list[Notification]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with SessionLocal() as session:
        result = await session.execute(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.sent_at >= cutoff)
            .order_by(Notification.sent_at.desc())
        )
        return list(result.scalars().all())


async def total_listings_since(days: int) -> int:
    from sqlalchemy import func

    cutoff = datetime.utcnow() - timedelta(days=days)
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.count(Listing.id)).where(Listing.fetched_at >= cutoff.isoformat())
        )
        return int(result.scalar() or 0)


def _percentile(sorted_values: list[float], k: float) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    return sorted_values[min(n - 1, int(k * (n - 1)))]


async def prices_by_model() -> list[dict]:
    """Текущая цена каждого объявления сгруппирована по модели.

    Возвращает медиану, среднее, Q1/Q3, min/max и число объявлений
    по каждой модели. Читает только price_raw из listings.
    """
    from collections import defaultdict

    async with SessionLocal() as session:
        result = await session.execute(
            select(Listing.model, Listing.price_raw).where(
                Listing.model != "",
                Listing.price_raw.is_not(None),
            )
        )
        by_model: dict[str, list[float]] = defaultdict(list)
        for model, price in result.all():
            by_model[model].append(price)

    out = []
    for model, prices in by_model.items():
        prices.sort()
        n = len(prices)
        total = sum(prices)
        out.append(
            {
                "model": model,
                "count": n,
                "avg": round(total / n),
                "median": _percentile(prices, 0.50),
                "q1": _percentile(prices, 0.25),
                "q3": _percentile(prices, 0.75),
                "min": prices[0],
                "max": prices[-1],
            }
        )
    out.sort(key=lambda x: (-x["count"], x["model"]))
    return out


async def delay_stats(days: int = 3) -> dict:
    """Задержка доставки уведомлений: время публикации -> момент отправки.

    Считается как sent_at - found_at для всех уведомлений за период.
    Чисто агрегирующий запрос, не трогает цикл шедулера.
    Если админ сбрасывал статистику, учитываются только уведомления после сброса.
    """
    from datetime import datetime as _dt, timezone as _tz

    cutoff = _dt.now(_tz.utc) - timedelta(days=days)
    reset_since = await get_meta("delay_stats_since")
    if reset_since:
        try:
            reset_dt = _dt.fromisoformat(reset_since.replace("Z", "+00:00"))
            if reset_dt.tzinfo is None:
                reset_dt = reset_dt.replace(tzinfo=_tz.utc)
            if reset_dt > cutoff:
                cutoff = reset_dt
        except ValueError:
            pass

    async with SessionLocal() as session:
        result = await session.execute(
            select(Notification.sent_at, Listing.found_at)
            .join(Listing, Listing.id == Notification.listing_id)
            .where(Notification.sent_at >= cutoff)
        )

    delays: list[int] = []
    for sent, found in result.all():
        if not sent or not found:
            continue
        try:
            found_dt = (
                _dt.fromisoformat(found.replace("Z", "+00:00"))
                if isinstance(found, str)
                else found
            )
            if found_dt.tzinfo is None:
                found_dt = found_dt.replace(tzinfo=_tz.utc)
            sent_dt = sent if sent.tzinfo else sent.replace(tzinfo=_tz.utc)
            delays.append(max(0, int((sent_dt - found_dt).total_seconds())))
        except (ValueError, TypeError):
            continue

    if not delays:
        return {"count": 0, "median": 0, "avg": 0, "p90": 0, "max": 0}

    delays.sort()
    return {
        "count": len(delays),
        "median": _percentile(delays, 0.50),
        "avg": round(sum(delays) / len(delays)),
        "p90": _percentile(delays, 0.90),
        "max": delays[-1],
    }


# --- Служебные метаданные ----------------------------------------------------

async def get_meta(key: str) -> Optional[str]:
    async with SessionLocal() as session:
        row = await session.get(AppMeta, key)
        return row.value if row else None


async def set_meta(key: str, value: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(AppMeta, key)
        if row is None:
            session.add(AppMeta(key=key, value=value))
        else:
            row.value = value
        await session.commit()


async def reset_delay_stats() -> None:
    """Обнуляет окно статистики задержек без удаления уведомлений.

    Дедуп-записи (notifications) остаются на месте — повторных отправок нет,
    но delay_stats будет считать только новые уведомления.
    """
    from datetime import datetime as _dt, timezone as _tz

    await set_meta("delay_stats_since", _dt.now(_tz.utc).isoformat())
