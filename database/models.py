from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Пользователь бота. id = Telegram user_id."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    access_level: Mapped[str] = mapped_column(String(16), default="free")  # free/premium/vip/admin
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)


class UserSettings(Base):
    """Правило отслеживания: модель + фильтры для конкретного пользователя."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    model: Mapped[str] = mapped_column(String(64), default="")  # "" = все модели
    min_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cities: Mapped[str] = mapped_column(String(512), default="Минск")  # через запятую
    check_interval: Mapped[int] = mapped_column(Integer, default=300)  # секунды
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    send_photos: Mapped[bool] = mapped_column(Boolean, default=True)
    show_description: Mapped[bool] = mapped_column(Boolean, default=True)


class Listing(Base):
    """Глобальная таблица всех найденных объявлений (дедупликация)."""

    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    price: Mapped[str] = mapped_column(String(64), default="")
    price_raw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    city: Mapped[str] = mapped_column(String(128), default="")
    url: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    storage: Mapped[str] = mapped_column(String(64), default="")
    images: Mapped[str] = mapped_column(Text, default="[]")  # JSON-список URL
    found_at: Mapped[str] = mapped_column(String(32), default="")
    fetched_at: Mapped[str] = mapped_column(String(32), default="")


class SavedListing(Base):
    """Избранное пользователя."""

    __tablename__ = "saved_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    listing_id: Mapped[str] = mapped_column(String(64), index=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_saved_user_listing"),
    )


class Notification(Base):
    """Факт отправки объявления пользователю (дедуп уведомлений)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    listing_id: Mapped[str] = mapped_column(String(64), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_notif_user_listing"),
    )
