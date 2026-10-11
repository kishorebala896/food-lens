"""Healthier alternatives: same category, better score, same scoring rules.

Strategy: OFF category tags run broad -> specific ("en:spreads",
"en:sweet-spreads", "en:confectionary-based-spreads"). Start at the most
specific one, pull the popular products there, score them with the exact same
rubric, and keep the ones that beat the original by a real margin. Not enough?
Walk one level broader. Popularity sorting keeps the suggestions to things
you can actually buy, not some obscure artisanal jar.
"""

from __future__ import annotations

from typing import Optional

from off_client import OFFError, search_category
from risks import find_risks
from score import score_product

MIN_GAIN = 10        # an "alternative" 2 points better isn't worth suggesting
MAX_RESULTS = 6
MAX_LEVELS = 3       # how far up the category tree to walk
# too broad to mean "the same kind of product"
TOO_BROAD = {"en:beverages", "en:foods", "en:plant-based-foods-and-beverages",
             "en:plant-based-foods", "en:snacks", "en:sweet-snacks", "en:salty-snacks",
             "en:breakfasts", "en:groceries", "en:dairies", "en:meals",
             "en:fermented-foods", "en:fermented-milk-products", "en:condiments"}


def _trustworthy(c: dict, original: dict) -> bool:
    """Crowdsourced records with gaps score optimistically, and a suggestion
    built on missing data is worse than no suggestion."""
    n = c["nutriments"]
    if any(n.get(k) is None for k in ("sugars", "saturated_fat", "salt")):
        return False
    if c["nova_group"] is None:
        return False
    # sanity check against OFF's own Nutri-Score: never suggest something it
    # grades worse than what you already have
    mine, theirs = original.get("nutriscore_grade"), c["nutriscore_grade"]
    return not (mine and theirs and theirs > mine)


def find_alternatives(product: dict, product_score: Optional[int]) -> dict:
    cats = [c for c in product.get("categories") or [] if c not in TOO_BROAD]
    floor = (product_score or 0) + MIN_GAIN
    if product_score is None:
        floor = 60  # no baseline to beat: just suggest decent picks
    seen = {product["barcode"]}
    picks, used_category = [], None

    for category in list(reversed(cats))[:MAX_LEVELS]:
        try:
            candidates = search_category(category)
        except OFFError:
            continue
        for c in candidates:
            key = (c["name"].lower(), tuple(b.lower() for b in c["brands"]))
            if (c["barcode"] in seen or key in seen or c["name"] == "Unknown product"
                    or not _trustworthy(c, product)):
                continue
            seen.update((c["barcode"], key))  # same product, many barcodes
            s = score_product(c, find_risks(c))
            if s["score"] is not None and s["score"] >= floor:
                picks.append({
                    "barcode": c["barcode"], "name": c["name"], "brands": c["brands"],
                    "quantity": c["quantity"], "image_url": c["image_small_url"],
                    "nutriscore_grade": c["nutriscore_grade"],
                    "score": s["score"], "band": s["band"], "color": s["color"],
                })
        used_category = used_category or (category if picks else None)
        if len(picks) >= MAX_RESULTS:
            break

    picks.sort(key=lambda p: -p["score"])
    return {"category": used_category.split(":", 1)[1].replace("-", " ")
            if used_category else None,
            "alternatives": picks[:MAX_RESULTS]}
