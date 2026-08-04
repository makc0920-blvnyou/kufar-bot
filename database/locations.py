import json
import os

_LOCATIONS_PATH = os.path.join(os.path.dirname(__file__), "kufar_locations.json")

with open(_LOCATIONS_PATH, encoding="utf-8") as _f:
    LOCATIONS: dict[str, dict] = json.load(_f)
    # {"Брестская область": {"id": "1", "areas": {"Брест": "1", ...}}, ...}

# Имена регионов (для точного матчинга городов)
REGION_NAMES: set[str] = set(LOCATIONS.keys())
