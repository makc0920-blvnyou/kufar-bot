import os

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Значение без кавычек и пробелов по краям (Render/paste-proof)."""
    return (os.getenv(name, default) or "").strip().strip('"').strip("'")


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


BOT_TOKEN: str = _env("BOT_TOKEN", "")

# --- Админ-панель -----------------------------------------------------------
raw_admin_ids = _env("ADMIN_IDS", _env("ADMIN_CHAT_ID", ""))
ADMIN_IDS: list[int] = [int(x.strip()) for x in raw_admin_ids.split(",") if x.strip()]

# --- Legacy single-chat (резервные чаты) ------------------------------------
CHAT_ID: int = _env_int("CHAT_ID", 0)

raw_additional = _env("ADDITIONAL_CHAT_IDS", "")
ADDITIONAL_CHAT_IDS: list[int] = [int(x.strip()) for x in raw_additional.split(",") if x.strip()]

ALL_CHAT_IDS: list[int] = ([CHAT_ID] + ADDITIONAL_CHAT_IDS) if CHAT_ID else ADDITIONAL_CHAT_IDS

# --- База данных (Neon PostgreSQL) ------------------------------------------
DATABASE_URL: str = _env(
    "DATABASE_URL",
    "sqlite+aiosqlite:///data/kufar.db",
)

# --- Планировщик -------------------------------------------------------------
CHECK_LOOP_SECONDS: int = _env_int("CHECK_LOOP_SECONDS", 15)  # тик цикла
MIN_KUFAR_INTERVAL_SECONDS: int = _env_int("MIN_KUFAR_INTERVAL_SECONDS", 15)  # рейт-лимит API
KUFAR_CACHE_TTL_SECONDS: int = _env_int("KUFAR_CACHE_TTL_SECONDS", 30)  # кэш списка
DEFAULT_CHECK_INTERVAL_SECONDS: int = _env_int("DEFAULT_CHECK_INTERVAL_SECONDS", 300)

# --- Парсер ------------------------------------------------------------------
KEYWORDS: str = _env("KEYWORDS", "iPhone")
MAX_ITEMS_PER_CHECK: int = _env_int("MAX_ITEMS_PER_CHECK", 30)
DATABASE_PATH: str = _env("DATABASE_PATH", "data/listings.db")

# --- Доступ ------------------------------------------------------------------
ALLOW_SELF_REGISTER: bool = _env("ALLOW_SELF_REGISTER", "true").lower() == "true"
DEFAULT_ACCESS_LEVEL: str = _env("DEFAULT_ACCESS_LEVEL", "free")

ACCESS_LIMITS: dict[str, dict[str, int]] = {
    "free": {"max_models": 1, "min_interval": 300},
    "premium": {"max_models": 10, "min_interval": 60},
    "vip": {"max_models": 999, "min_interval": 15},
}

# --- Mini App -----------------------------------------------------------------
_render_base = _env("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBAPP_BASE: str = _env("WEBAPP_BASE", _render_base or "https://kufar-bot-i9w9.onrender.com").rstrip("/")
WEBAPP_URL: str = f"{WEBAPP_BASE}/app"

# --- Rate limiting бота ------------------------------------------------------
COMMAND_RATE_LIMIT_PER_MIN: int = _env_int("COMMAND_RATE_LIMIT_PER_MIN", 10)

# --- Доп. фильтры по умолчанию -----------------------------------------------
MIN_PRICE_GLOBAL: float = _env_float("MIN_PRICE_GLOBAL", 95)  # дешёвый мусор
