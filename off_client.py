"""Open Food Facts lookup. Free API, no key, 3M+ products, crowdsourced.

Which is great, except crowdsourced also means half the fields are missing on
any given product — so every field access here is guarded. Learned that the
hard way.
"""

from __future__ import annotations

import time

import requests

API_URL = "https://world.openfoodfacts.org/api/v2/product"
FIELDS = (
    "product_name,brands,quantity,image_url,ingredients_text,"
    "nutriments,nutriscore_grade,nova_group,additives_tags,allergens_tags"
)
# OFF 403s generic/bot user-agents. This one got through.
USER_AGENT = "food-lens/0.1 (personal learning project; contact via GitHub)"
TIMEOUT = 10


def _get_float(d: dict, key: str) -> float | None:
    try:
        return float(d.get(key)) if d.get(key) is not None else None
    except (TypeError, ValueError):
        return None


def lookup(barcode: str) -> dict | None:
    """Fetch a product by barcode. Returns a normalized dict, or None if the
    barcode isn't in the database (OFF answers HTTP 200 with status: 0)."""
    barcode = (barcode or "").strip().replace(" ", "")
    if not barcode:
        return None

    url = f"{API_URL}/{barcode}.json?fields={FIELDS}"
    headers = {"User-Agent": USER_AGENT}

    last_err = None
    for _ in range(2):  # one retry, then give up
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.RequestException, ValueError) as e:
            last_err = e
            time.sleep(1)
    else:
        raise RuntimeError(f"Open Food Facts request failed: {last_err}")

    if data.get("status") != 1:
        return None

    p = data.get("product") or {}
    nutr = p.get("nutriments") or {}

    # per-100g values are what the scoring works on; any of these can be absent
    nutriments = {
        "sugars": _get_float(nutr, "sugars_100g"),
        "saturated_fat": _get_float(nutr, "saturated-fat_100g"),
        "salt": _get_float(nutr, "salt_100g"),
        "sodium": _get_float(nutr, "sodium_100g"),
        "fiber": _get_float(nutr, "fiber_100g"),
        "protein": _get_float(nutr, "proteins_100g"),
        "energy_kcal": _get_float(nutr, "energy-kcal_100g"),
    }
    # salt sometimes comes only as sodium — convert (salt = sodium * 2.5)
    if nutriments["salt"] is None and nutriments["sodium"] is not None:
        nutriments["salt"] = nutriments["sodium"] * 2.5

    nova = p.get("nova_group")
    try:
        nova = int(nova) if nova is not None else None
    except (TypeError, ValueError):
        nova = None

    brands = p.get("brands") or ""
    return {
        "barcode": barcode,
        "name": p.get("product_name") or "Unknown product",
        "brands": [b.strip() for b in brands.split(",") if b.strip()],
        "quantity": p.get("quantity"),
        "image_url": p.get("image_url"),
        "ingredients_text": p.get("ingredients_text"),
        "nutriments": nutriments,
        "nutriscore_grade": (p.get("nutriscore_grade") or "").upper() or None,
        "nova_group": nova,
        "additives": [t.replace("en:", "") for t in (p.get("additives_tags") or [])],
        "allergens": [t.replace("en:", "") for t in (p.get("allergens_tags") or [])],
    }
