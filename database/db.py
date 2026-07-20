import os

import aiosqlite
from loguru import logger

from datetime import datetime, timedelta

from config import DATABASE_PATH


async def init_db() -> None:
    db_dir = os.path.dirname(DATABASE_PATH) or "."
    os.makedirs(db_dir, exist_ok=True)

    logger.debug("Инициализация базы данных")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                price TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                found_at TEXT NOT NULL DEFAULT ''
            )
            """
        )

        for col_def in [
            "model TEXT NOT NULL DEFAULT ''",
            "storage TEXT NOT NULL DEFAULT ''",
            "price_raw REAL",
            "fetched_at TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                await db.execute(f"ALTER TABLE listings ADD COLUMN {col_def}")
            except Exception:
                pass

        await db.execute("DROP TABLE IF EXISTS user_prices")
        await db.execute(
            """
            CREATE TABLE user_prices (
                chat_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                price REAL NOT NULL,
                PRIMARY KEY (chat_id, model)
            )
            """
        )

        await db.commit()

    logger.info("База данных инициализирована")


async def get_user_price(chat_id: int, model: str) -> float | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT price FROM user_prices WHERE chat_id = ? AND model = ?",
            (chat_id, model),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_user_price(chat_id: int, model: str, price: float) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO user_prices (chat_id, model, price)
            VALUES (?, ?, ?)
            """,
            (chat_id, model, price),
        )
        await db.commit()


async def get_all_user_prices(chat_id: int) -> dict[str, float]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT model, price FROM user_prices WHERE chat_id = ?",
            (chat_id,),
        )
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}


KNOWN_MODELS: list[str] = [
    "iPhone 7", "iPhone 7 Plus",
    "iPhone 8", "iPhone 8 Plus",
    "iPhone X", "iPhone XR", "iPhone XS", "iPhone XS Max",
    "iPhone 11", "iPhone 11 Pro", "iPhone 11 Pro Max",
    "iPhone SE (2-го поколения)",
    "iPhone 12", "iPhone 12 mini", "iPhone 12 Pro", "iPhone 12 Pro Max",
    "iPhone 13", "iPhone 13 mini", "iPhone 13 Pro", "iPhone 13 Pro Max",
    "iPhone SE (3-го поколения)",
    "iPhone 14", "iPhone 14 Plus", "iPhone 14 Pro", "iPhone 14 Pro Max",
    "iPhone 15", "iPhone 15 Plus", "iPhone 15 Pro", "iPhone 15 Pro Max",
    "iPhone 16", "iPhone 16 Plus", "iPhone 16 Pro", "iPhone 16 Pro Max", "iPhone 16e",
    "iPhone 17", "iPhone 17 Pro", "iPhone 17 Pro Max",
    "iPhone Air", "iPhone 17e",
]


async def get_distinct_models() -> list[str]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT model FROM listings WHERE model != ''"
        )
        rows = await cursor.fetchall()
        db_models = set(r[0] for r in rows)
    all_models = set(KNOWN_MODELS) | db_models
    return sorted(all_models)


async def is_listing_exists(listing_id: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM listings WHERE id = ?",
            (listing_id,),
        )
        return await cursor.fetchone() is not None


async def save_listing(
    listing_id: str,
    title: str,
    price: str,
    city: str,
    url: str,
    description: str,
    found_at: str,
    model: str = "",
    storage: str = "",
    price_raw: float | None = None,
    fetched_at: str = "",
) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO listings
                (id, title, price, city, url, description, found_at, model, storage, price_raw, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (listing_id, title, price, city, url, description, found_at, model, storage, price_raw, fetched_at),
        )
        await db.commit()


async def get_recent_prices_for_group(model: str, storage: str, hours: int = 12) -> list[float]:
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT price_raw FROM listings
            WHERE model = ? AND storage = ? AND price_raw IS NOT NULL
              AND fetched_at >= ?
            ORDER BY price_raw
            """,
            (model, storage, cutoff),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


def calc_quartiles(prices: list[float]) -> tuple[float, float, float]:
    n = len(prices)
    if n == 0:
        return (0.0, 0.0, 0.0)
    s = sorted(prices)

    def pct(k):
        idx = max(0, min(n - 1, int(k * (n - 1))))
        return s[idx]

    return (pct(0.25), pct(0.50), pct(0.75))


async def get_total_listings() -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM listings")
        row = await cursor.fetchone()
        return row[0] if row else 0
