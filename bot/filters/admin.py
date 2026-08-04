from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import Message

from config import ADMIN_IDS
from database.db import get_user


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user_id = message.from_user.id if message.from_user else None
        if user_id is None:
            return False
        if user_id in ADMIN_IDS:
            return True
        db_user = await get_user(user_id)
        return bool(db_user and db_user.access_level == "admin")
