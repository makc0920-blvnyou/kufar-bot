"""Временный эндпоинт миграции Neon → Railway PostgreSQL.

Временно добавляется в main.py, вызывается один раз, потом удаляется.
Доступен только по токену: GET /api/migrate?token=SECRET
"""
import os
from aiohttp import web
from sqlalchemy import text

MIGRATE_TOKEN = os.environ.get("MIGRATE_TOKEN", "migrate-once-2026")
NEON_URL = os.environ.get("NEON_URL", "")  # отдельная переменная

async def handle_migrate(request: web.Request) -> web.Response:
    token = request.query.get("token", "")
    if token != MIGRATE_TOKEN:
        return web.Response(status=403, text="bad token")

    from database.db import engine as dst_engine_raw
    from sqlalchemy.ext.asyncio import create_async_engine

    if not NEON_URL:
        return web.Response(text="NEON_URL not set")

    src = create_async_engine(NEON_URL.replace("postgresql://", "postgresql+asyncpg://"))
    dst = dst_engine_raw  # текущий engine (Railway PostgreSQL)

    TABLES = ["users", "user_settings", "listings", "notifications", "saved_listings", "hidden_models", "app_meta"]
    results = []

    async with src.connect() as src_conn:
        for table in TABLES:
            try:
                rows = (await src_conn.execute(text(f"SELECT * FROM {table}"))).mappings().all()
                if not rows:
                    results.append(f"{table}: 0 (пусто)")
                    continue
                cols = list(rows[0].keys())
                cols_sql = ", ".join(cols)
                placeholders = ", ".join(f":{c}" for c in cols)
                async with dst.begin() as dst_conn:
                    for row in rows:
                        await dst_conn.execute(
                            text(f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"),
                            dict(row),
                        )
                results.append(f"{table}: {len(rows)} ✓")
            except Exception as e:
                results.append(f"{table}: ОШИБКА — {e}")

    await src.dispose()
    return web.Response(text="\n".join(results))
