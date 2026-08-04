from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_listing_keyboard(listing: dict, setting_id: int | None = None) -> InlineKeyboardMarkup:
    url = listing.get("url", "#")
    listing_id = listing.get("id", "")
    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🔗 Открыть объявление", url=url)],
    ]
    row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="⭐ В избранное", callback_data=f"save:{listing_id}"),
    ]
    if setting_id:
        row.append(
            InlineKeyboardButton(
                text="⏸️ Пауза для модели",
                callback_data=f"pause:{setting_id}",
            )
        )
    buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить модель",
                    callback_data="settings:add_model",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Мои модели",
                    callback_data="settings:list_models",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏸️ Пауза всех",
                    callback_data="settings:pause_all",
                ),
                InlineKeyboardButton(
                    text="▶️ Возобновить",
                    callback_data="settings:resume_all",
                ),
            ],
        ]
    )
