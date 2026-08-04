from datetime import date, datetime, timedelta

from database.db import (
    count_notifications_for_user,
    count_settings_for_user,
    get_recent_price_raw,
    get_settings_for_user,
    list_hidden_models,
    notifications_since,
)
from database.models import User


def _quartiles(prices: list[float]) -> tuple[float, float, float]:
    n = len(prices)
    if n == 0:
        return 0.0, 0.0, 0.0
    s = sorted(prices)

    def pct(k: float) -> float:
        idx = max(0, min(n - 1, int(k * (n - 1))))
        return s[idx]

    return pct(0.25), pct(0.50), pct(0.75)


async def build_user_stats(user: User) -> dict:
    settings = await get_settings_for_user(user.id)
    notified = await count_notifications_for_user(user.id)
    hidden = await list_hidden_models(user.id)
    active = sum(1 for s in settings if s.is_active)

    models = []
    for s in settings[:10]:
        prices = await get_recent_price_raw(s.model)
        q1, q2, q3 = _quartiles(prices)
        models.append(
            {
                "id": s.id,
                "model": s.model,
                "is_active": s.is_active,
                "min_price": s.min_price,
                "max_price": s.max_price,
                "cities": s.cities,
                "check_interval": s.check_interval,
                "median": q2,
                "q1": q1,
                "q3": q3,
                "market_count": len(prices),
                "market_max": max(prices) if prices else None,
            }
        )

    week = await notifications_since(user.id, 7)
    by_day: dict[str, int] = {}
    for n in week:
        day = n.sent_at.strftime("%d.%m") if n.sent_at else "?"
        by_day[day] = by_day.get(day, 0) + 1
    week_sorted = [
        {"day": d, "count": c}
        for d, c in sorted(by_day.items(), reverse=True)
    ]

    return {
        "username": user.username,
        "first_name": user.first_name,
        "access_level": user.access_level,
        "models_count": len(settings),
        "active_count": active,
        "notified": notified,
        "hidden": hidden,
        "models": models,
        "week": week_sorted,
    }


async def format_user_stats(user: User) -> str:
    settings = await get_settings_for_user(user.id)
    notified = await count_notifications_for_user(user.id)
    active = sum(1 for s in settings if s.is_active)
    hidden = await list_hidden_models(user.id)

    lines = [
        f"📊 <b>Статистика</b>",
        f"👤 {user.username or user.first_name or user.id}",
        f"⭐ Уровень: {user.access_level}",
        f"📋 Моделей: {len(settings)} (активно: {active})",
        f"📨 Уведомлений отправлено: {notified}",
        f"🙈 Скрытых моделей: {len(hidden)}",
        "",
    ]

    if settings:
        lines.append("<b>Модели и рынок (медиана за 12ч):</b>")
        for s in settings[:10]:
            prices = await get_recent_price_raw(s.model)
            q1, q2, q3 = _quartiles(prices)
            status = "🟢" if s.is_active else "🔴"
            if prices:
                lines.append(
                    f"{status} <b>{s.model}</b> — мед. {q2:,.0f} | "
                    f"Q1 {q1:,.0f} | макс {max(prices):,.0f} | n={len(prices)}"
                )
            else:
                lines.append(f"{status} <b>{s.model}</b> — нет данных рынка")

    week = await notifications_since(user.id, 7)
    if week:
        days: dict[str, int] = {}
        for n in week:
            day = n.sent_at.strftime("%d.%m") if n.sent_at else "?"
            days[day] = days.get(day, 0) + 1
        lines.append("\n<b>За неделю:</b>")
        for day in sorted(days, reverse=True):
            lines.append(f"  {day}: {days[day]} 📨")

    return "\n".join(lines)


async def format_admin_dashboard() -> str:
    from database.db import count_listings, list_active_users, list_users, total_listings_since

    users = await list_users()
    active = await list_active_users()
    total_listings = await count_listings()
    new_7d = await total_listings_since(7)

    lines = [
        "📈 <b>Дашборд</b>",
        f"👥 Пользователей: {len(users)} (активных: {len(active)})",
        f"📦 Объявлений в базе: {total_listings}",
        f"🆕 Новых за 7 дней: {new_7d}",
    ]
    return "\n".join(lines)
