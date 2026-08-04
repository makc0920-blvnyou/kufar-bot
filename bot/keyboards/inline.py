from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.db import DEFAULT_LIMIT_MODELS

MODELS_PER_PAGE = 8

INTERVAL_PRESETS = [
    (15, "15 сек"),
    (60, "1 мин"),
    (300, "5 мин"),
    (1800, "30 мин"),
    (3600, "1 час"),
    (86400, "24 часа"),
]


# --- Уведомления -------------------------------------------------------------

def build_listing_keyboard(listing: dict, setting_id: int | None = None) -> InlineKeyboardMarkup:
    url = listing.get("url", "#")
    listing_id = listing.get("id", "")
    model = (listing.get("model") or "").strip()
    buttons: list[list[InlineKeyboardButton]] = []
    phones = listing.get("phones") or []
    if phones:
        buttons.append([InlineKeyboardButton(text="📞 Позвонить", url=f"tel:{phones[0]}")])
    buttons.append([InlineKeyboardButton(text="🔗 Открыть объявление", url=url)])
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
    if model:
        row.append(
            InlineKeyboardButton(text="❌ Скрыть похожие", callback_data=f"hide:{model}")
        )
    buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Настройки ---------------------------------------------------------------

def _rule_label(setting) -> str:
    state = "🟢" if setting.is_active else "🔴"
    price = (
        f"{setting.min_price:,.0f}–{setting.max_price:,.0f}"
        if setting.max_price
        else f"от {setting.min_price:,.0f}"
    )
    return f"{state} {setting.model} — {price} BYN"


def build_settings_menu(settings) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for s in settings:
        buttons.append(
            [InlineKeyboardButton(text=_rule_label(s), callback_data=f"ed:b:{s.id}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="➕ Добавить модель", callback_data="s:add")]
    )
    if settings:
        buttons.append(
            [InlineKeyboardButton(text="🗑 Остановить все", callback_data="s:clr")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_model_browser(page: int) -> InlineKeyboardMarkup:
    total = len(DEFAULT_LIMIT_MODELS)
    pages = max(1, (total + MODELS_PER_PAGE - 1) // MODELS_PER_PAGE)
    page = max(0, min(page, pages - 1))

    start = page * MODELS_PER_PAGE
    chunk = DEFAULT_LIMIT_MODELS[start : start + MODELS_PER_PAGE]

    buttons: list[list[InlineKeyboardButton]] = []
    for idx, model in enumerate(chunk):
        buttons.append(
            [InlineKeyboardButton(text=model, callback_data=f"mp:{start + idx}")]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"mb:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"mb:{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="s:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_model_detail(setting) -> InlineKeyboardMarkup:
    sid = setting.id
    active = "🔕 Пауза" if setting.is_active else "▶️ Возобновить"
    photos = "✅" if setting.send_photos else "❌"
    desc = "✅" if setting.show_description else "❌"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Изменить цену", callback_data=f"ed:p:{sid}")],
            [InlineKeyboardButton(text="📍 Города", callback_data=f"ed:c:{sid}")],
            [InlineKeyboardButton(text="⏱ Интервал", callback_data=f"ed:i:{sid}")],
            [
                InlineKeyboardButton(text=f"🖼 Фото {photos}", callback_data=f"ed:f:{sid}"),
                InlineKeyboardButton(text=f"📄 Описание {desc}", callback_data=f"ed:g:{sid}"),
            ],
            [
                InlineKeyboardButton(text=active, callback_data=f"ed:t:{sid}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"ed:d:{sid}"),
            ],
            [InlineKeyboardButton(text="◀️ В список", callback_data="s:back")],
        ]
    )


def build_interval_menu(setting_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{label}", callback_data=f"ed:ip:{setting_id}:{value}"
            )
        ]
        for value, label in INTERVAL_PRESETS
    ]
    buttons.append([InlineKeyboardButton(text="✍️ Свой", callback_data=f"ed:ic:{setting_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"ed:b:{setting_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Админ -------------------------------------------------------------------

def build_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="am:u")],
            [InlineKeyboardButton(text="➕ Выдать доступ", callback_data="am:g")],
            [InlineKeyboardButton(text="📣 Рассылка", callback_data="am:b")],
        ]
    )


def _user_state_icon(u) -> str:
    if u.access_level == "pending":
        return "⏳"
    return "🟢" if u.is_active and not u.is_blocked else "🔴"


def build_users_list(users, page: int) -> InlineKeyboardMarkup:
    per_page = 6
    total = len(users)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = users[page * per_page : page * per_page + per_page]

    buttons: list[list[InlineKeyboardButton]] = []
    for u in chunk:
        state = _user_state_icon(u)
        name = u.username or u.first_name or str(u.id)
        buttons.append(
            [InlineKeyboardButton(text=f"{state} {name}", callback_data=f"aui:{u.id}")]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"au:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"au:{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="◀️ В админку", callback_data="am:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_user_actions(user) -> InlineKeyboardMarkup:
    uid = user.id
    block_btn = (
        InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"aui:blk:{uid}")
        if not user.is_blocked
        else InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"aui:unb:{uid}")
    )
    rows: list[list[InlineKeyboardButton]] = []
    if user.access_level == "pending":
        rows.append(
            [InlineKeyboardButton(text="✅ Одобрить (free)", callback_data=f"aui:appr:{uid}")]
        )
    rows.append(
        [
            InlineKeyboardButton(text="💎 premium", callback_data=f"aui:lvl:{uid}:premium"),
            InlineKeyboardButton(text="👑 vip", callback_data=f"aui:lvl:{uid}:vip"),
        ]
    )
    rows.append([InlineKeyboardButton(text="📊 Статистика", callback_data=f"aui:stat:{uid}")])
    rows.append([block_btn])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="am:u")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
