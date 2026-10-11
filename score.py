"""Deterministic 0-100 health score from per-100g nutriments.

Deliberate design choice: the LLM never touches this math. Scoring is fixed
rules so it's reproducible, testable, and you can argue with it in an
interview. The model only gets to explain the breakdown this produces.

Not a dietitian's rubric — just a reasonable one. Nutri-Score thresholds
informed the cutoffs; drinks get stricter sugar bands (per 100ml, sugar in a
drink is a much bigger deal than in a solid).
"""

from __future__ import annotations

from typing import Optional

from risks import HIGH, LOW, MODERATE, unique_additives

RISK_POINTS = {HIGH: 6, MODERATE: 3, LOW: 1}
ADDITIVE_CAP = 25

# (limit, penalty): first threshold the value exceeds wins
SUGAR_FOOD = [(45, 30), (22.5, 20), (12.5, 12), (5, 5)]  # >45g: it's mostly sugar
SUGAR_DRINK = [(8, 20), (4, 12), (1.5, 6)]
SAT_FAT = [(10, 15), (5, 10), (1.5, 4)]
SALT = [(1.5, 15), (0.9, 10), (0.3, 4)]

# UK FSA "traffic light" cutoffs (low/high) per 100g, for the nutrient table
LEVELS_FOOD = {"fat": (3, 17.5), "saturated_fat": (1.5, 5),
               "sugars": (5, 22.5), "salt": (0.3, 1.5)}
LEVELS_DRINK = {"fat": (1.5, 8.75), "saturated_fat": (0.75, 2.5),
                "sugars": (2.5, 11.25), "salt": (0.3, 0.75)}


def _band(value: float, thresholds: list) -> float:
    for limit, penalty in thresholds:
        if value > limit:
            return penalty
    return 0.0


def is_beverage(product: dict) -> bool:
    cats = set(product.get("categories") or [])
    return "en:beverages" in cats and "en:plant-milks" not in cats


def nutrient_table(product: dict) -> list:
    """Per-100g nutrient rows for the UI, each with a low/moderate/high level
    where a traffic-light rule exists (fiber/protein: higher is better)."""
    n = product.get("nutriments") or {}
    levels = LEVELS_DRINK if is_beverage(product) else LEVELS_FOOD
    rows = []
    for key, label, unit in (("energy_kcal", "Energy", "kcal"), ("fat", "Fat", "g"),
                             ("saturated_fat", "Saturated fat", "g"),
                             ("sugars", "Sugars", "g"), ("salt", "Salt", "g"),
                             ("fiber", "Fiber", "g"), ("protein", "Protein", "g")):
        v = n.get(key)
        if v is None:
            continue
        level = None
        if key in levels:
            lo, hi = levels[key]
            level = "high" if v > hi else ("moderate" if v > lo else "low")
        elif key == "fiber":
            level = "good" if v >= 3 else None
        elif key == "protein":
            level = "good" if v >= 8 else None
        rows.append({"key": key, "label": label, "value": round(v, 2),
                     "unit": unit, "level": level})
    return rows


def score_product(product: dict, risks: Optional[list] = None) -> dict:
    """Returns {"score": 0-100 | None, "band", "color", "factors", "confidence"}.
    Each factor: {"label", "points" (+/-), "detail"} — this breakdown is what
    the explainer consumes, so keep the details concrete."""
    factors = []
    score = 100.0
    n = product.get("nutriments") or {}
    drink = is_beverage(product)
    risks = risks or []

    def add(label, points, detail):
        nonlocal score
        score += points
        if points:  # don't clutter the breakdown with ±0 rows
            factors.append({"label": label, "points": round(points, 1),
                            "detail": detail})

    unit = "100ml" if drink else "100g"

    sugars = n.get("sugars")
    if sugars is not None:
        p = -_band(sugars, SUGAR_DRINK if drink else SUGAR_FOOD)
        hint = ""
        if p <= -12:
            hint = " — basically a soft drink" if drink else " — that's dessert territory"
        add("Sugar", p, f"{sugars:g}g sugar per {unit}{hint}")

    sat = n.get("saturated_fat")
    if sat is not None:
        add("Saturated fat", -_band(sat, SAT_FAT), f"{sat:g}g saturated fat per {unit}")

    salt = n.get("salt")
    if salt is not None:
        add("Salt", -_band(salt, SALT), f"{salt:g}g salt per {unit}")

    fiber = n.get("fiber")
    if fiber is not None:
        p = 10 if fiber >= 6 else (5 if fiber >= 3 else 0)
        add("Fiber", p, f"{fiber:g}g fiber per {unit} — rare for packaged food, genuinely good")

    protein = n.get("protein")
    if protein is not None:
        p = 8 if protein >= 16 else (4 if protein >= 8 else 0)
        add("Protein", p, f"{protein:g}g protein per {unit}")

    nova = product.get("nova_group")
    if nova == 4:
        add("Ultra-processed (NOVA 4)", -15,
            "NOVA group 4: industrial formulation, not just food + cooking")
    elif nova == 3:
        add("Processed (NOVA 3)", -7, "NOVA group 3: processed, but recognizable ingredients")

    # risky additives/ingredients weigh by level; harmless-ish additives 1pt each
    risk_pts = sum(RISK_POINTS[r["level"]] for r in risks)
    flagged = {r["code"].lower() for r in risks if r.get("code")}
    others = [a for a in unique_additives(product.get("additives") or [])
              if a not in flagged]
    if risks:
        names = ", ".join(r["name"] for r in risks[:4]) + ("…" if len(risks) > 4 else "")
        add("Risky ingredients", -min(ADDITIVE_CAP, risk_pts),
            f"{len(risks)} flagged: {names}")
    if others:
        room = max(0, ADDITIVE_CAP - risk_pts)
        shown = ", ".join(a.upper() for a in others[:4]) + ("…" if len(others) > 4 else "")
        add("Other additives", -min(room, len(others)),
            f"{len(others)} more additive(s): {shown}")

    # missing data is normal (crowdsourced) — say so instead of pretending
    missing = [k for k, v in (("sugar", sugars), ("saturated fat", sat), ("salt", salt))
               if v is None]
    if missing:
        factors.append({"label": "Missing data", "points": 0,
                        "detail": f"no {', '.join(missing)} data reported — score may be optimistic"})

    if len(missing) == 3:
        # no core nutrition at all: a number here would be fiction
        return {"score": None, "band": "not enough data", "color": "#757575",
                "factors": factors, "confidence": "none"}

    score = max(0.0, min(100.0, round(score)))
    if score >= 80:
        band, color = "solid choice", "#2e7d32"
    elif score >= 60:
        band, color = "okay, in moderation", "#9c8a00"
    elif score >= 40:
        band, color = "treat territory", "#e65100"
    else:
        band, color = "dessert, basically", "#b71c1c"

    return {"score": int(score), "band": band, "color": color, "factors": factors,
            "confidence": "low" if missing else "high"}
