import json
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from database.models import (
    Base,
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
    """Neon отдаёт postgresql:// — переводим на asyncpg-драйвер."""
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(
    _normalize_db_url(DATABASE_URL),
    echo=False,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"БД инициализирована: {_normalize_db_url(DATABASE_URL)}")


# --- Пользователи ------------------------------------------------------------

async def get_user(user_id: int) -> Optional[User]:
    async with SessionLocal() as session:
        return await session.get(User, user_id)


async def ensure_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    access_level: str = "free",
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
        await session.commit()
        await session.refresh(user)
        return user


async def revoke_access(user_id: int) -> None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.is_blocked = True
            user.is_active = False
            await session.commit()


async def set_access_level(user_id: int, level: str) -> None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.access_level = level
            await session.commit()


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


async def record_notification(user_id: int, listing_id: str) -> None:
    async with SessionLocal() as session:
        session.add(Notification(user_id=user_id, listing_id=listing_id))
        await session.commit()


async def count_notifications_for_user(user_id: int) -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Notification).where(Notification.user_id == user_id)
        )
        return len(result.scalars().all())
