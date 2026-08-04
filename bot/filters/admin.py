from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from database.db import get_user


async def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if user_id in ADMIN_IDS:
        return True
    db_user = await get_user(user_id)
    return bool(db_user and db_user.access_level == "admin")


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user_id = message.from_user.id if message.from_user else None
        return await _is_admin(user_id)


class CallbackIsAdmin(BaseFilter):
    async def __call__(self, callback: CallbackQuery) -> bool:
        user_id = callback.from_user.id if callback.from_user else None
        return await _is_admin(user_id)
