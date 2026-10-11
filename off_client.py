"""Open Food Facts lookup + search. Free API, no key, 3M+ products, crowdsourced.

Which is great, except crowdsourced also means half the fields are missing on
any given product — so every field access here is guarded. Learned that the
hard way.

Two hosts:
- world.openfoodfacts.org  — product-by-barcode (v2) and a category search fallback
- search.openfoodfacts.org — "search-a-licious", the fast Elasticsearch-backed
  search. The legacy /cgi/search.pl is flaky (often serves a maintenance page).
"""

from __future__ import annotations

import re
import time
from functools import lru_cache
from typing import Optional

import requests

PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product"
V2_SEARCH_URL = "https://world.openfoodfacts.org/api/v2/search"
SEARCH_URL = "https://search.openfoodfacts.org/search"

# Everything scoring + risk detection needs. Search hits use the same list so
# results can be scored without a second request per product.
FIELDS = (
    "code,product_name,product_name_en,generic_name,brands,quantity,image_front_url,"
    "image_front_small_url,image_url,ingredients_text,nutriments,"
    "nutriscore_grade,nova_group,additives_tags,allergens_tags,"
    "categories_tags,ingredients_analysis_tags,ingredients_tags"
)
# OFF 403s generic/bot user-agents. This one got through.
USER_AGENT = "food-lens/0.2 (personal learning project; contact via GitHub)"
TIMEOUT = 10

_CANONICAL_TAG = re.compile(r"^en:[a-z0-9-]+$")
_ADDITIVE_TAG = re.compile(r"^en:e\d{3,4}[a-z]*$")

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


class OFFError(RuntimeError):
    """Upstream (Open Food Facts) failed — distinct from 'product not found'."""


def _get_json(url: str, params: Optional[dict] = None,
              not_found_ok: bool = False) -> Optional[dict]:
    last_err = None
    for attempt in range(2):  # one retry, then give up
        try:
            resp = _session.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code == 404 and not_found_ok:
                return None  # v2 sometimes 404s unknown barcodes instead of status: 0
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last_err = e
            if attempt == 0:
                time.sleep(0.6)
    raise OFFError(f"Open Food Facts request failed: {last_err}")


def _get_float(d: dict, key: str) -> Optional[float]:
    try:
        return float(d.get(key)) if d.get(key) is not None else None
    except (TypeError, ValueError):
        return None


def _strip_lang(tag: str) -> str:
    return tag.split(":", 1)[1] if ":" in tag else tag


def normalize(p: dict, barcode: Optional[str] = None) -> dict:
    """Raw OFF product (from the product API *or* a search hit) -> our shape."""
    nutr = p.get("nutriments") or {}

    # per-100g values are what the scoring works on; any of these can be absent
    nutriments = {
        "energy_kcal": _get_float(nutr, "energy-kcal_100g"),
        "fat": _get_float(nutr, "fat_100g"),
        "saturated_fat": _get_float(nutr, "saturated-fat_100g"),
        "sugars": _get_float(nutr, "sugars_100g"),
        "salt": _get_float(nutr, "salt_100g"),
        "sodium": _get_float(nutr, "sodium_100g"),
        "fiber": _get_float(nutr, "fiber_100g"),
        "protein": _get_float(nutr, "proteins_100g"),
    }
    # salt sometimes comes only as sodium — convert (salt = sodium * 2.5)
    if nutriments["salt"] is None and nutriments["sodium"] is not None:
        nutriments["salt"] = round(nutriments["sodium"] * 2.5, 3)

    nova = p.get("nova_group")
    try:
        nova = int(nova) if nova is not None else None
    except (TypeError, ValueError):
        nova = None

    brands = p.get("brands") or ""
    if isinstance(brands, list):  # search-a-licious returns a list
        brands = ",".join(brands)

    grade = (p.get("nutriscore_grade") or "").lower()
    # only canonical taxonomy tags; OFF also carries unmatched user text like
    # "en:Petit-déjeuners", which is useless for category queries
    categories = [t for t in (p.get("categories_tags") or [])
                  if _CANONICAL_TAG.match(t)]
    ingredient_tags = [t for t in (p.get("ingredients_tags") or []) if t.startswith("en:")]

    additives = p.get("additives_tags")
    if additives is None:
        # search hits don't carry additives_tags, but E-numbers show up as
        # ingredient tags ("en:e322")
        additives = [t for t in ingredient_tags if _ADDITIVE_TAG.match(t)]

    return {
        "barcode": barcode or str(p.get("code") or ""),
        "name": (p.get("product_name_en") or p.get("product_name")
                 or p.get("generic_name") or "").strip() or "Unknown product",
        "brands": [b.strip() for b in brands.split(",") if b.strip()],
        "quantity": p.get("quantity"),
        "image_url": p.get("image_front_url") or p.get("image_url"),
        "image_small_url": (p.get("image_front_small_url") or p.get("image_front_url")
                            or p.get("image_url")),
        "ingredients_text": p.get("ingredients_text"),
        "nutriments": nutriments,
        # OFF uses "unknown"/"not-applicable" as grades; only a-e are real
        "nutriscore_grade": grade.upper() if grade in "abcde" and grade else None,
        "nova_group": nova,
        "additives": [_strip_lang(t) for t in additives],
        "allergens": [_strip_lang(t) for t in (p.get("allergens_tags") or [])],
        "categories": categories,
        "ingredients_analysis": [_strip_lang(t) for t in
                                 (p.get("ingredients_analysis_tags") or [])],
        "ingredient_tags": [_strip_lang(t) for t in ingredient_tags],
    }


def clean_barcode(barcode: str) -> str:
    return "".join(ch for ch in (barcode or "") if ch.isdigit())


@lru_cache(maxsize=512)
def lookup(barcode: str) -> Optional[dict]:
    """Fetch a product by barcode. Returns a normalized dict, or None if the
    barcode isn't in the database (OFF answers status: 0, or sometimes 404)."""
    barcode = clean_barcode(barcode)
    if not barcode:
        return None

    candidates = [barcode]
    # scanners read UPC-A as 12 digits; OFF usually files them as EAN-13 with a
    # leading zero (and vice versa)
    if len(barcode) == 12:
        candidates.append("0" + barcode)
    elif len(barcode) == 13 and barcode.startswith("0"):
        candidates.append(barcode[1:])

    for code in candidates:
        data = _get_json(f"{PRODUCT_URL}/{code}.json", {"fields": FIELDS},
                         not_found_ok=True)
        if data and data.get("status") == 1 and data.get("product"):
            p = normalize(data["product"], code)
            # empty stubs (someone scanned it once, nobody filled anything in)
            # are "not found" as far as a shopper is concerned
            if (p["name"] == "Unknown product" and not p["image_url"]
                    and not p["ingredients_text"]
                    and all(v is None for v in p["nutriments"].values())):
                continue
            return p
    return None


def search(query: str, page: int = 1, page_size: int = 20) -> dict:
    """Keyword search. Returns {"products": [...normalized], "page", "page_count"}."""
    data = _get_json(SEARCH_URL, {
        "q": query, "page": page, "page_size": page_size,
        "fields": FIELDS, "langs": "en",
    }) or {}
    products = [normalize(h) for h in data.get("hits") or [] if h.get("code")]
    products = [p for p in products if p["name"] != "Unknown product"]
    return {"products": products, "page": data.get("page", page),
            "page_count": data.get("page_count", 1)}


def search_category(category: str, page_size: int = 60) -> list:
    """Popular products in one category (e.g. "en:sweet-spreads").
    search-a-licious first, v2 search as a fallback."""
    try:
        data = _get_json(SEARCH_URL, {
            "q": f'categories_tags:"{category}"', "page_size": page_size,
            "fields": FIELDS, "sort_by": "-unique_scans_n",
        }) or {}
        hits = data.get("hits") or []
    except OFFError:
        data = _get_json(V2_SEARCH_URL, {
            "categories_tags": category, "page_size": page_size,
            "fields": FIELDS, "sort_by": "unique_scans_n",
        }) or {}
        hits = data.get("products") or []
    return [normalize(h) for h in hits if h.get("code")]
