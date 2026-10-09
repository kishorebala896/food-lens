"""Deterministic 0-100 health score from per-100g nutriments.

Deliberate design choice: the LLM never touches this math. Scoring is fixed
rules so it's reproducible, testable, and you can argue with it in an
interview. The model only gets to explain the breakdown this produces.

Not a dietitian's rubric — just a reasonable one. Nutri-Score thresholds
informed the cutoffs.
"""

from __future__ import annotations


def _band(points_lost: float, thresholds: list[tuple[float, float]]) -> float:
    """Stepped penalty: first threshold the value exceeds wins."""
    for limit, penalty in thresholds:
        if points_lost > limit:
            return penalty
    return 0.0


def score_product(nutriments: dict, nova_group: int | None,
                  additives: list[str]) -> dict:
    """Returns {"score": 0-100, "band": str, "color": str, "factors": [...]}.
    Each factor: {"label", "points" (+/-), "detail"} — this breakdown is what
    the explainer consumes, so keep the details concrete."""
    factors = []
    score = 100.0
    n = nutriments or {}

    def add(label, points, detail):
        nonlocal score
        score += points
        if points:  # don't clutter the breakdown with ±0 rows
            factors.append({"label": label, "points": round(points, 1),
                            "detail": detail})

    sugars = n.get("sugars")
    if sugars is not None:
        p = -_band(sugars, [(22.5, 20), (12.5, 12), (5, 5)])
        add("Sugar", p,
            f"{sugars:g}g sugar per 100g" + (" — that's dessert territory" if p <= -12 else ""))

    sat = n.get("saturated_fat")
    if sat is not None:
        p = -_band(sat, [(10, 15), (5, 10), (1.5, 4)])
        add("Saturated fat", p, f"{sat:g}g saturated fat per 100g")

    salt = n.get("salt")
    if salt is not None:
        p = -_band(salt, [(1.5, 15), (0.9, 10), (0.3, 4)])
        add("Salt", p, f"{salt:g}g salt per 100g")

    fiber = n.get("fiber")
    if fiber is not None:
        p = 10 if fiber >= 6 else (5 if fiber >= 3 else 0)
        if p:
            add("Fiber", p, f"{fiber:g}g fiber per 100g — rare for packaged food, genuinely good")

    protein = n.get("protein")
    if protein is not None:
        p = 8 if protein >= 16 else (4 if protein >= 8 else 0)
        if p:
            add("Protein", p, f"{protein:g}g protein per 100g")

    if nova_group == 4:
        add("Ultra-processed (NOVA 4)", -15,
            "NOVA group 4: industrial formulation, not just food + cooking")
    elif nova_group == 3:
        add("Processed (NOVA 3)", -7, "NOVA group 3: processed, but recognizable ingredients")

    if additives:
        p = -min(15, 3 * len(additives))
        shown = ", ".join(additives[:4])
        add("Additives", p,
            f"{len(additives)} additive(s){': ' + shown if shown else ''}"
            + ("…" if len(additives) > 4 else ""))

    # missing data is normal (crowdsourced) — say so instead of pretending
    known = [k for k, v in
             (("sugar", sugars), ("saturated fat", sat), ("salt", salt))
             if v is None]
    if known:
        factors.append({"label": "Missing data", "points": 0,
                        "detail": f"no {', '.join(known)} data reported — score may be optimistic"})

    score = max(0.0, min(100.0, round(score)))
    if score >= 80:
        band, color = "solid choice", "#2e7d32"
    elif score >= 60:
        band, color = "okay, in moderation", "#9c8a00"
    elif score >= 40:
        band, color = "treat territory", "#e65100"
    else:
        band, color = "dessert, basically", "#b71c1c"

    return {"score": score, "band": band, "color": color, "factors": factors}
