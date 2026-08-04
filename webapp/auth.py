import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Any


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict[str, Any] | None:
    """Проверяет подпись Telegram WebApp initData и возвращает параметры.

    Схема: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data:
        return None

    try:
        params = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    provided_hash = params.pop("hash", None)
    if not provided_hash:
        return None

    try:
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(params.items())
        )
        calculated = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
    except Exception:
        return None

    if not hmac.compare_digest(calculated, provided_hash):
        return None

    try:
        if time.time() - int(params.get("auth_date", 0)) > max_age:
            return None
    except (ValueError, TypeError):
        return None

    return params


def extract_user(validated: dict[str, Any] | None) -> dict[str, Any] | None:
    """Достаёт user из валидированного initData."""
    if not validated:
        return None
    try:
        user = json.loads(validated.get("user") or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    if not user or not user.get("id"):
        return None
    return user
