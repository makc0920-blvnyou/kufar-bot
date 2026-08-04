import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# --- Админ-панель -----------------------------------------------------------
raw_admin_ids = os.getenv("ADMIN_IDS", os.getenv("ADMIN_CHAT_ID", ""))
ADMIN_IDS: list[int] = [int(x.strip()) for x in raw_admin_ids.split(",") if x.strip()]

# --- Legacy single-chat (резервные чаты) ------------------------------------
raw_chat = os.getenv("CHAT_ID", "0")
CHAT_ID: int = int(raw_chat) if raw_chat.strip() else 0

raw_additional = os.getenv("ADDITIONAL_CHAT_IDS", "")
ADDITIONAL_CHAT_IDS: list[int] = [int(x.strip()) for x in raw_additional.split(",") if x.strip()]

ALL_CHAT_IDS: list[int] = ([CHAT_ID] + ADDITIONAL_CHAT_IDS) if CHAT_ID else ADDITIONAL_CHAT_IDS

# --- База данных (Neon PostgreSQL) ------------------------------------------
# Пример: postgresql://user:pass@ep-xxx.neon.tech/dbname?sslmode=require
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///data/kufar.db",
)

# --- Планировщик -------------------------------------------------------------
CHECK_LOOP_SECONDS: int = int(os.getenv("CHECK_LOOP_SECONDS", "15"))  # тик цикла
MIN_KUFAR_INTERVAL_SECONDS: int = int(os.getenv("MIN_KUFAR_INTERVAL_SECONDS", "15"))  # рейт-лимит API
KUFAR_CACHE_TTL_SECONDS: int = int(os.getenv("KUFAR_CACHE_TTL_SECONDS", "30"))  # кэш списка
DEFAULT_CHECK_INTERVAL_SECONDS: int = int(os.getenv("DEFAULT_CHECK_INTERVAL_SECONDS", "300"))

# --- Парсер ------------------------------------------------------------------
KEYWORDS: str = os.getenv("KEYWORDS", "iPhone")
MAX_ITEMS_PER_CHECK: int = int(os.getenv("MAX_ITEMS_PER_CHECK", "30"))
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/listings.db")

# --- Доступ ------------------------------------------------------------------
ALLOW_SELF_REGISTER: bool = os.getenv("ALLOW_SELF_REGISTER", "true").lower() == "true"
DEFAULT_ACCESS_LEVEL: str = os.getenv("DEFAULT_ACCESS_LEVEL", "free")

ACCESS_LIMITS: dict[str, dict[str, int]] = {
    "free": {"max_models": 1, "min_interval": 300},
    "premium": {"max_models": 10, "min_interval": 60},
    "vip": {"max_models": 999, "min_interval": 15},
}

# --- Rate limiting бота ------------------------------------------------------
COMMAND_RATE_LIMIT_PER_MIN: int = int(os.getenv("COMMAND_RATE_LIMIT_PER_MIN", "10"))

# --- Доп. фильтры по умолчанию -----------------------------------------------
MIN_PRICE_GLOBAL: float = float(os.getenv("MIN_PRICE_GLOBAL", "95"))  # дешёвый мусор
