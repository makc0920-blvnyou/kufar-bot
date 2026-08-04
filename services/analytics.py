from datetime import datetime

from database.db import (
    count_notifications_for_user,
    count_settings_for_user,
    get_settings_for_user,
    get_recent_price_raw,
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


async def format_user_stats(user: User) -> str:
    settings = await get_settings_for_user(user.id)
    notified = await count_notifications_for_user(user.id)
    active = sum(1 for s in settings if s.is_active)

    lines = [
        f"📊 <b>Статистика</b>",
        f"👤 {user.username or user.first_name or user.id}",
        f"⭐ Уровень: {user.access_level}",
        f"📋 Моделей: {len(settings)} (активно: {active})",
        f"📨 Уведомлений отправлено: {notified}",
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

    return "\n".join(lines)
