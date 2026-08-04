from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from loguru import logger

from config import ADMIN_IDS, ALLOW_SELF_REGISTER, COMMAND_RATE_LIMIT_PER_MIN
from database.db import ensure_user, get_user


def _answer(event: Message | CallbackQuery, text: str) -> Awaitable[Any]:
    if isinstance(event, CallbackQuery):
        return event.answer(text=text, show_alert=True)
    return event.answer(text)


def _user_id(event: Message | CallbackQuery) -> int | None:
    u = getattr(event, "from_user", None)
    return u.id if u is not None else None


class AuthMiddleware(BaseMiddleware):
    """Whitelist: только зарегистрированные/активные пользователи."""

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_id = _user_id(event)
        if user_id is None:
            return

        user = getattr(event, "from_user", None)
        username = user.username if user else None
        first_name = user.first_name if user else None

        # Админ всегда пропускается
        if user_id in ADMIN_IDS:
            await ensure_user(user_id, username, first_name, is_admin=True)
            data["db_user"] = await get_user(user_id)
            return await handler(event, data)

        db_user = await get_user(user_id)

        if db_user is None:
            if ALLOW_SELF_REGISTER:
                db_user = await ensure_user(user_id, username, first_name)
                logger.info(f"Новый пользователь: {user_id} (@{username or '—'})")
            else:
                await _answer(event, "🚫 Нет доступа. Свяжитесь с администратором.")
                return

        if db_user.is_blocked or not db_user.is_active:
            await _answer(event, "🚫 Доступ заблокирован.")
            return

        data["db_user"] = db_user
        return await handler(event, data)


class ThrottlingMiddleware(BaseMiddleware):
    """Rate limit: не более N событий в минуту на пользователя."""

    def __init__(self, limit_per_min: int = COMMAND_RATE_LIMIT_PER_MIN) -> None:
        self._limit = limit_per_min
        self._stamps: dict[int, list[float]] = {}
        self._window = 60.0
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_id = _user_id(event)
        if user_id is not None:
            import time

            now = time.monotonic()
            stamps = [t for t in self._stamps.get(user_id, []) if now - t < self._window]
            if len(stamps) >= self._limit:
                # ВАЖНО: отвечаем на callback, иначе кнопка Telegram «висит»
                if isinstance(event, CallbackQuery):
                    await event.answer("⏳ Не так быстро", show_alert=False)
                return
            stamps.append(now)
            self._stamps[user_id] = stamps
        return await handler(event, data)
