from typing import Any

import httpx
from loguru import logger

from config import KEYWORDS, MAX_ITEMS_PER_CHECK

KUFAR_API_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"

HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.kufar.by/",
    "Origin": "https://www.kufar.by",
    "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


async def fetch_listings(
    keywords: str | None = None,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "query": keywords or KEYWORDS,
        "size": max_items or MAX_ITEMS_PER_CHECK,
        "sort": "lst.d",
        "lang": "ru",
    }

    async with httpx.AsyncClient() as client:
        try:
            logger.debug(f"Запрос к Куфару: {KUFAR_API_URL}")
            response = await client.get(
                KUFAR_API_URL,
                params=params,
                headers=HEADERS,
                timeout=15.0,
            )

            logger.debug(f"Статус ответа: {response.status_code}")

            response.raise_for_status()

            if not response.headers.get("content-type", "").startswith("application/json"):
                logger.error("Куфар вернул не JSON (возможно, капча или блокировка)")
                return []

            data = response.json()

        except httpx.TimeoutException:
            logger.warning("Таймаут при запросе к API Куфара")
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
            return []
        except Exception as e:
            logger.error(f"Ошибка при запросе: {e}")
            return []

    items = _extract_items(data)
    logger.info(f"Получено {len(items)} объявлений")
    return items


def _extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = data.get("ads")
    if raw_items is None:
        logger.warning("В ответе нет ключа 'ads'")
        return []

    result = []
    for item in raw_items:
        parsed = parse_listing_raw(item)
        if parsed is not None:
            result.append(parsed)

    return result


def _extract_price(ad: dict[str, Any]) -> str:
    calculator = ad.get("calculator", [])
    price_map = {e["currency"]: e["price"] for e in calculator if e.get("price")}

    byn = price_map.get("BYN")
    if byn and byn != "0":
        return f"{float(byn) / 100:,.2f} BYN".replace(",", " ")

    usd = price_map.get("USD")
    if usd and usd != "0":
        return f"${float(usd) / 100:,.2f}".replace(",", " ")

    for cur in ("EUR", "RUB"):
        val = price_map.get(cur)
        if val and val != "0":
            return f"{float(val) / 100:,.2f} {cur}".replace(",", " ")

    return "Цена не указана"


def _extract_city(ad: dict[str, Any]) -> str:
    region = ""
    area = ""
    for param in ad.get("ad_parameters", []):
        p = param.get("p", "")
        val = param.get("vl") or ""
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val)
        if p == "region":
            region = str(val) if val else ""
        elif p == "area":
            area = str(val) if val else ""
    if area and area != region:
        return f"{region}, {area}"
    return region or "Город не указан"


import re as _re

_PHONE_RE = _re.compile(
    r"(?:\+?375[\s\-\(\)]{0,4}\d{2}[\s\-\(\)]{0,4}\d{3}[\s\-\(\)]{0,4}\d{2}[\s\-\(\)]{0,4}\d{2}"
    r"|\+?375\d{9}"
    r"|8\s?\(\s?0?\d{2}\s?\)[\s\-]{0,4}\d{3}[\s\-]{0,4}\d{2}[\s\-]{0,4}\d{2}"
    r"|8\s?0\s?\d{2}[\s\-]{0,4}\d{7})"
)


def _normalize_phone(raw: str) -> str | None:
    digits = _re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+375") and len(digits) == 13:
        return digits
    if digits.startswith("375") and len(digits) == 12:
        return "+" + digits
    if digits.startswith("80") and len(digits) == 11:
        return "+375" + digits[1:].lstrip("0")
    return None


def _extract_phones(raw: dict[str, Any]) -> list[str]:
    texts = [
        raw.get("subject", ""),
        raw.get("body") or "",
        raw.get("body_short") or "",
    ]
    texts += [str(p.get("v") or p.get("vl") or "") for p in raw.get("ad_parameters", [])]
    text = " ".join(t for t in texts if t)

    found: list[str] = []
    for m in _PHONE_RE.finditer(text):
        ph = _normalize_phone(m.group(0))
        if ph and ph not in found:
            found.append(ph)
    return found


def format_phone(phone: str) -> str:
    d = _re.sub(r"[^\d]", "", phone)
    if not d.startswith("375") or len(d) != 12:
        return phone
    return f"+{d[0:3]} ({d[3:5]}) {d[5:8]}-{d[8:10]}-{d[10:12]}"


_NEXT_DATA_RE = _re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', _re.S)


async def fetch_listing_details(listing_id: str) -> dict[str, Any]:
    """Дотягивает полное описание и телефон со страницы объявления.

    Поисковое API Куфара присылает body=None, поэтому для новых объявлений
    берём описание из SSR-разметки страницы.
    """
    import json

    import httpx as _httpx

    try:
        async with _httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                f"https://www.kufar.by/item/{listing_id}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Accept-Language": "ru-RU,ru;q=0.9",
                },
                timeout=15.0,
            )
            if response.status_code != 200:
                return {}
            html = response.text
    except Exception as e:
        logger.debug(f"Не удалось получить страницу объявления {listing_id}: {e}")
        return {}

    m = _NEXT_DATA_RE.search(html)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
        initial = data["props"]["initialState"]["adView"]["data"]["initial"]
    except (KeyError, TypeError, ValueError):
        return {}

    if not isinstance(initial, dict):
        return {}

    result: dict[str, Any] = {}
    body = (initial.get("body") or "").strip()
    if body:
        result["description"] = body[:2000]
    phones = _extract_phones(initial)
    if phones:
        result["phones"] = phones
    return result


def _extract_battery(raw: dict[str, Any]) -> str | None:
    text = " ".join([
        raw.get("subject", ""),
        raw.get("body") or "",
        raw.get("body_short") or "",
    ])

    patterns = [
        r'(?:АКБ|батаре[ия]|battery|аккумулятор|износ)\s*[:\s]*(\d{2,3})\s*%',
        r'(\d{2,3})\s*%\s*(?:АКБ|батаре[ия]|battery|аккумулятор|износ|health)',
        r'состояни[ея]\s*(?:АКБ|батареи|battery)?\s*[:\s]*(\d{2,3})\s*%',
        r'battery\s*health\s*[:\s]*(\d{2,3})\s*%',
    ]
    for pat in patterns:
        m = _re.search(pat, text, _re.IGNORECASE)
        if m:
            return f"{m.group(1)}%"

    m = _re.search(r'(?<!\d)(\d{2,3})\s*%(?!\d)', text)
    if m:
        return f"{m.group(1)}%"

    return None


def _extract_model(ad: dict[str, Any]) -> str:
    for p in ad.get("ad_parameters", []):
        if p.get("p") == "phones_model":
            return str(p.get("vl", ""))
    return ""


def _extract_storage(ad: dict[str, Any]) -> str:
    for p in ad.get("ad_parameters", []):
        if p.get("p") == "phablet_phones_memory":
            raw = str(p.get("vl", ""))
            m = _re.search(r'(\d+)\s*', raw)
            if m:
                return f"{m.group(1)} ГБ"
    return ""


def _extract_images(raw: dict[str, Any]) -> list[str]:
    images = raw.get("images", [])
    result = []
    for img in images:
        path = img.get("path", "")
        if path:
            result.append(f"https://rms.kufar.by/v1/gallery/{path}")
    return result


def _is_private(raw: dict[str, Any]) -> bool:
    return not raw.get("company_ad", False)


def parse_listing_raw(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not _is_private(raw):
        return None

    ad_id = str(raw.get("ad_id") or raw.get("list_id") or "")

    return {
        "id": ad_id,
        "title": raw.get("subject", "Без названия"),
        "price": _extract_price(raw),
        "city": _extract_city(raw),
        "url": raw.get("ad_link") or f"https://www.kufar.by/item/{ad_id}",
        "description": (raw.get("body") or raw.get("body_short") or "")[:2000],
        "date": raw.get("list_time", ""),
        "images": _extract_images(raw),
        "battery": _extract_battery(raw),
        "model": _extract_model(raw),
        "storage": _extract_storage(raw),
        "price_raw": _extract_price_raw(raw),
        "phones": _extract_phones(raw),
    }


def _extract_price_raw(ad: dict[str, Any]) -> float | None:
    calculator = ad.get("calculator", [])
    price_map = {e["currency"]: e["price"] for e in calculator if e.get("price")}
    byn = price_map.get("BYN")
    if byn and byn != "0":
        return float(byn) / 100.0
    usd = price_map.get("USD")
    if usd and usd != "0":
        return float(usd) / 100.0
    return None
