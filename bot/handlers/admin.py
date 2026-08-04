from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from loguru import logger

from bot.filters.admin import IsAdmin
from bot.keyboards.inline import build_settings_menu
from database.db import (
    find_user_by_username,
    grant_access,
    list_active_users,
    list_users,
    revoke_access,
    set_access_level,
)
from services.analytics import format_user_stats
from services.notification import broadcast

router = Router()

LEVELS = ("free", "premium", "vip")


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message) -> None:
    await message.answer(
        "🛠 <b>Админ-панель</b>\n\n"
        "/users — список пользователей\n"
        "/grant_access @username или ID — выдать доступ\n"
        "/revoke_access @username или ID — заблокировать\n"
        "/set_level @username free|premium|vip — уровень\n"
        "/broadcast сообщение — рассылка всем активным\n"
        "/user_stats @username — статистика юзера"
    )


@router.message(Command("users"), IsAdmin())
async def cmd_users(message: Message) -> None:
    users = await list_users()
    if not users:
        await message.answer("Пользователей пока нет.")
        return

    lines = ["👥 <b>Пользователи</b>\n"]
    for u in users:
        state = "🟢" if u.is_active and not u.is_blocked else "🔴"
        access = {
            "free": "free",
            "premium": "💎 premium",
            "vip": "👑 vip",
            "admin": "🛠 admin",
        }.get(u.access_level, u.access_level)
        models_count = len(await __count_models(u.id))
        name = u.username or u.first_name or str(u.id)
        lines.append(
            f"{state} <b>{name}</b>\n"
            f"   ID: <code>{u.id}</code> | {access} | моделей: {models_count}"
        )
    await message.answer("\n\n".join(lines))


async def __count_models(user_id: int) -> list:
    from database.db import get_settings_for_user

    return await get_settings_for_user(user_id)


async def _resolve_target(message: Message, arg: str) -> int | None:
    """Возвращает user_id по @username или по числовому ID."""
    arg = arg.strip()
    if arg.isdigit():
        return int(arg)
    user = await find_user_by_username(arg)
    if user is None:
        await message.answer(
            f"❌ Пользователь {arg} не найден. Он должен сначала написать боту /start."
        )
        return None
    return user.id


@router.message(Command("grant_access"), IsAdmin())
async def cmd_grant_access(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        await message.answer("Формат: <code>/grant_access @username или 123456789 [level]</code>")
        return
    target_id = await _resolve_target(message, args[0])
    if target_id is None:
        return
    level = args[1] if len(args) > 1 and args[1] in LEVELS else "free"
    user = await grant_access(target_id, access_level=level)
    await message.answer(
        f"✅ Доступ выдан\nID: <code>{user.id}</code>\nУровень: {user.access_level}"
    )
    try:
        await message.bot.send_message(
            target_id,
            f"🎉 Вам выдан доступ к Kufar Monitor! Уровень: {level}\n\n"
            "Добавьте модель: <code>/add_model iPhone 15 600 1200</code>",
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить {target_id}: {e}")


@router.message(Command("revoke_access"), IsAdmin())
async def cmd_revoke_access(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        await message.answer("Формат: <code>/revoke_access @username или 123456789</code>")
        return
    target_id = await _resolve_target(message, args[0])
    if target_id is None:
        return
    await revoke_access(target_id)
    await message.answer(f"🚫 Доступ отозван: <code>{target_id}</code>")


@router.message(Command("set_level"), IsAdmin())
async def cmd_set_level(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if len(args) < 2:
        await message.answer("Формат: <code>/set_level @username free|premium|vip</code>")
        return
    level = args[1].lower()
    if level not in LEVELS:
        await message.answer(f"❌ Уровни: {', '.join(LEVELS)}")
        return
    target_id = await _resolve_target(message, args[0])
    if target_id is None:
        return
    await set_access_level(target_id, level)
    await message.answer(f"✅ Уровень {target_id}: {level}")


@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast(message: Message, command: CommandObject) -> None:
    text = (command.args or "").strip()
    if not text:
        await message.answer("Формат: <code>/broadcast сообщение</code>")
        return
    users = await list_active_users()
    ids = [u.id for u in users]
    if not ids:
        await message.answer("Нет активных пользователей.")
        return
    sent = await broadcast(message.bot, ids, text)
    await message.answer(f"📣 Отправлено {sent} из {len(ids)} пользователям.")


@router.message(Command("user_stats"), IsAdmin())
async def cmd_user_stats(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        await message.answer("Формат: <code>/user_stats @username или 123456789</code>")
        return
    target_id = await _resolve_target(message, args[0])
    if target_id is None:
        return
    from database.db import get_user

    target = await get_user(target_id)
    if target is None:
        await message.answer("Пользователь не найден.")
        return
    text = await format_user_stats(target)
    await message.answer(text)
