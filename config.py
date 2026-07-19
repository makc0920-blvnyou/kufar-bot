import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

raw_chat = os.getenv("CHAT_ID", "0")
CHAT_ID: int = int(raw_chat) if raw_chat.strip() else 0

raw_additional = os.getenv("ADDITIONAL_CHAT_IDS", "")
ADDITIONAL_CHAT_IDS: list[int] = [
    int(x.strip()) for x in raw_additional.split(",") if x.strip()
]

ALL_CHAT_IDS: list[int] = [CHAT_ID] + ADDITIONAL_CHAT_IDS if CHAT_ID else ADDITIONAL_CHAT_IDS

raw_admin = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_ID: int | None = int(raw_admin) if raw_admin and raw_admin.strip() else None

CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "2"))
KEYWORDS: str = os.getenv("KEYWORDS", "iPhone")
MAX_ITEMS_PER_CHECK: int = int(os.getenv("MAX_ITEMS_PER_CHECK", "30"))
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/listings.db")
