import os

import aiosqlite
from loguru import logger

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
        ]:
            try:
                await db.execute(f"ALTER TABLE listings ADD COLUMN {col_def}")
            except Exception:
                pass

        await db.commit()

    logger.info("База данных инициализирована")


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
) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO listings
                (id, title, price, city, url, description, found_at, model, storage, price_raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (listing_id, title, price, city, url, description, found_at, model, storage, price_raw),
        )
        await db.commit()


async def get_prices_for_group(model: str, storage: str) -> list[float]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT price_raw FROM listings
            WHERE model = ? AND storage = ? AND price_raw IS NOT NULL
            ORDER BY price_raw
            """,
            (model, storage),
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
