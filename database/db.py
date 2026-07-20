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

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_prices (
                chat_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                storage TEXT NOT NULL,
                price REAL NOT NULL,
                PRIMARY KEY (chat_id, model, storage)
            )
            """
        )

        await db.commit()

    logger.info("База данных инициализирована")


async def get_user_price(chat_id: int, model: str, storage: str) -> float | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT price FROM user_prices WHERE chat_id = ? AND model = ? AND storage = ?",
            (chat_id, model, storage),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_user_price(chat_id: int, model: str, storage: str, price: float) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO user_prices (chat_id, model, storage, price)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, model, storage, price),
        )
        await db.commit()


async def get_all_user_prices(chat_id: int) -> dict[tuple[str, str], float]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT model, storage, price FROM user_prices WHERE chat_id = ?",
            (chat_id,),
        )
        rows = await cursor.fetchall()
        return {(r[0], r[1]): r[2] for r in rows}


KNOWN_MODELS: list[tuple[str, str]] = [
    ("iPhone 7", "32 ГБ"), ("iPhone 7", "128 ГБ"), ("iPhone 7", "256 ГБ"),
    ("iPhone 7 Plus", "32 ГБ"), ("iPhone 7 Plus", "128 ГБ"), ("iPhone 7 Plus", "256 ГБ"),
    ("iPhone 8", "64 ГБ"), ("iPhone 8", "128 ГБ"), ("iPhone 8", "256 ГБ"),
    ("iPhone 8 Plus", "64 ГБ"), ("iPhone 8 Plus", "128 ГБ"), ("iPhone 8 Plus", "256 ГБ"),
    ("iPhone X", "64 ГБ"), ("iPhone X", "256 ГБ"),
    ("iPhone XR", "64 ГБ"), ("iPhone XR", "128 ГБ"), ("iPhone XR", "256 ГБ"),
    ("iPhone XS", "64 ГБ"), ("iPhone XS", "256 ГБ"), ("iPhone XS", "512 ГБ"),
    ("iPhone XS Max", "64 ГБ"), ("iPhone XS Max", "256 ГБ"), ("iPhone XS Max", "512 ГБ"),
    ("iPhone 11", "64 ГБ"), ("iPhone 11", "128 ГБ"), ("iPhone 11", "256 ГБ"),
    ("iPhone 11 Pro", "64 ГБ"), ("iPhone 11 Pro", "256 ГБ"), ("iPhone 11 Pro", "512 ГБ"),
    ("iPhone 11 Pro Max", "64 ГБ"), ("iPhone 11 Pro Max", "256 ГБ"), ("iPhone 11 Pro Max", "512 ГБ"),
    ("iPhone SE (2-го поколения)", "64 ГБ"), ("iPhone SE (2-го поколения)", "128 ГБ"), ("iPhone SE (2-го поколения)", "256 ГБ"),
    ("iPhone 12", "64 ГБ"), ("iPhone 12", "128 ГБ"), ("iPhone 12", "256 ГБ"),
    ("iPhone 12 mini", "64 ГБ"), ("iPhone 12 mini", "128 ГБ"), ("iPhone 12 mini", "256 ГБ"),
    ("iPhone 12 Pro", "128 ГБ"), ("iPhone 12 Pro", "256 ГБ"), ("iPhone 12 Pro", "512 ГБ"),
    ("iPhone 12 Pro Max", "128 ГБ"), ("iPhone 12 Pro Max", "256 ГБ"), ("iPhone 12 Pro Max", "512 ГБ"),
    ("iPhone 13", "128 ГБ"), ("iPhone 13", "256 ГБ"), ("iPhone 13", "512 ГБ"),
    ("iPhone 13 mini", "128 ГБ"), ("iPhone 13 mini", "256 ГБ"), ("iPhone 13 mini", "512 ГБ"),
    ("iPhone 13 Pro", "128 ГБ"), ("iPhone 13 Pro", "256 ГБ"), ("iPhone 13 Pro", "512 ГБ"), ("iPhone 13 Pro", "1 ТБ"),
    ("iPhone 13 Pro Max", "128 ГБ"), ("iPhone 13 Pro Max", "256 ГБ"), ("iPhone 13 Pro Max", "512 ГБ"), ("iPhone 13 Pro Max", "1 ТБ"),
    ("iPhone SE (3-го поколения)", "64 ГБ"), ("iPhone SE (3-го поколения)", "128 ГБ"), ("iPhone SE (3-го поколения)", "256 ГБ"),
    ("iPhone 14", "128 ГБ"), ("iPhone 14", "256 ГБ"), ("iPhone 14", "512 ГБ"),
    ("iPhone 14 Plus", "128 ГБ"), ("iPhone 14 Plus", "256 ГБ"), ("iPhone 14 Plus", "512 ГБ"),
    ("iPhone 14 Pro", "128 ГБ"), ("iPhone 14 Pro", "256 ГБ"), ("iPhone 14 Pro", "512 ГБ"), ("iPhone 14 Pro", "1 ТБ"),
    ("iPhone 14 Pro Max", "128 ГБ"), ("iPhone 14 Pro Max", "256 ГБ"), ("iPhone 14 Pro Max", "512 ГБ"), ("iPhone 14 Pro Max", "1 ТБ"),
    ("iPhone 15", "128 ГБ"), ("iPhone 15", "256 ГБ"), ("iPhone 15", "512 ГБ"),
    ("iPhone 15 Plus", "128 ГБ"), ("iPhone 15 Plus", "256 ГБ"), ("iPhone 15 Plus", "512 ГБ"),
    ("iPhone 15 Pro", "128 ГБ"), ("iPhone 15 Pro", "256 ГБ"), ("iPhone 15 Pro", "512 ГБ"), ("iPhone 15 Pro", "1 ТБ"),
    ("iPhone 15 Pro Max", "128 ГБ"), ("iPhone 15 Pro Max", "256 ГБ"), ("iPhone 15 Pro Max", "512 ГБ"), ("iPhone 15 Pro Max", "1 ТБ"),
    ("iPhone 16", "128 ГБ"), ("iPhone 16", "256 ГБ"), ("iPhone 16", "512 ГБ"),
    ("iPhone 16 Plus", "128 ГБ"), ("iPhone 16 Plus", "256 ГБ"), ("iPhone 16 Plus", "512 ГБ"),
    ("iPhone 16 Pro", "128 ГБ"), ("iPhone 16 Pro", "256 ГБ"), ("iPhone 16 Pro", "512 ГБ"), ("iPhone 16 Pro", "1 ТБ"),
    ("iPhone 16 Pro Max", "128 ГБ"), ("iPhone 16 Pro Max", "256 ГБ"), ("iPhone 16 Pro Max", "512 ГБ"), ("iPhone 16 Pro Max", "1 ТБ"),
    ("iPhone 16e", "128 ГБ"), ("iPhone 16e", "256 ГБ"), ("iPhone 16e", "512 ГБ"),
    ("iPhone 17", "256 ГБ"), ("iPhone 17", "512 ГБ"),
    ("iPhone 17 Pro", "256 ГБ"), ("iPhone 17 Pro", "512 ГБ"), ("iPhone 17 Pro", "1 ТБ"),
    ("iPhone 17 Pro Max", "256 ГБ"), ("iPhone 17 Pro Max", "512 ГБ"), ("iPhone 17 Pro Max", "1 ТБ"), ("iPhone 17 Pro Max", "2 ТБ"),
    ("iPhone Air", "256 ГБ"), ("iPhone Air", "512 ГБ"), ("iPhone Air", "1 ТБ"),
    ("iPhone 17e", "256 ГБ"), ("iPhone 17e", "512 ГБ"),
]


async def get_distinct_models() -> list[tuple[str, str]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT model, storage FROM listings WHERE model != '' AND storage != ''"
        )
        rows = await cursor.fetchall()
        db_models = set((r[0], r[1]) for r in rows)
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
