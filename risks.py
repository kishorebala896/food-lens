"""Risky-ingredient detection: additives (E-numbers) + a few ingredient patterns.

A small, curated table — not an encyclopedia. Each entry says *why* it's
flagged in one sentence, leaning on regulator positions (EFSA, IARC, FDA, EU
labelling rules) rather than vibes. Levels:

- high:     banned/restricted somewhere, carries a mandatory warning, or an
            IARC carcinogen classification tied to normal dietary exposure
- moderate: credible-but-debated concerns, or fine in small amounts
- low:      generally considered safe; flagged for sensitive people only

Anything not in the table still counts as "an additive" in the score, just
without a scary label. Lecithin and citric acid don't deserve a red badge.
"""

from __future__ import annotations

import re

HIGH, MODERATE, LOW = "high", "moderate", "low"

_SOUTHAMPTON = ("Azo/synthetic colour from the Southampton study; EU labels must "
                "warn it 'may have an adverse effect on activity and attention in children'.")
_NITRITE = ("Curing agent that can form nitrosamines; processed meat cured this way "
            "is an IARC Group 1 carcinogen (colorectal cancer).")
_PHOSPHATE = ("Added phosphates are almost fully absorbed; high intake is linked to "
              "cardiovascular and kidney strain.")
_ALUMINIUM = ("Aluminium-based additive; EFSA notes some people may exceed the "
              "tolerable weekly intake of aluminium.")
_SULPHITE = ("Sulphite — can trigger asthma-like reactions in sensitive people "
             "and destroys vitamin B1.")
_BENZOATE = ("Preservative that can form benzene alongside vitamin C; also "
             "studied for links to hyperactivity in children.")
_EMULSIFIER = ("Emulsifier shown to disrupt gut microbiota and promote low-grade "
               "inflammation in animal studies.")

# code -> (name, level, reason)
ADDITIVES: dict = {
    # colours
    "e102": ("Tartrazine", HIGH, _SOUTHAMPTON),
    "e104": ("Quinoline yellow", HIGH, _SOUTHAMPTON),
    "e110": ("Sunset yellow FCF", HIGH, _SOUTHAMPTON),
    "e122": ("Azorubine", HIGH, _SOUTHAMPTON),
    "e124": ("Ponceau 4R", HIGH, _SOUTHAMPTON),
    "e129": ("Allura red AC", HIGH, _SOUTHAMPTON),
    "e127": ("Erythrosine", HIGH, "Linked to thyroid tumours in rats; the US FDA revoked "
             "its authorisation in food (Red No. 3) in 2025."),
    "e171": ("Titanium dioxide", HIGH, "Banned as a food additive in the EU since 2022 — "
             "EFSA could no longer rule out genotoxicity."),
    "e150c": ("Ammonia caramel", MODERATE, "Can contain 4-MEI, classified possibly "
              "carcinogenic to humans (IARC 2B)."),
    "e150d": ("Sulphite ammonia caramel", MODERATE, "Can contain 4-MEI, classified "
              "possibly carcinogenic to humans (IARC 2B)."),
    "e133": ("Brilliant blue FCF", LOW, "Synthetic dye; rare allergic reactions reported."),
    # preservatives
    "e210": ("Benzoic acid", MODERATE, _BENZOATE),
    "e211": ("Sodium benzoate", MODERATE, _BENZOATE),
    "e212": ("Potassium benzoate", MODERATE, _BENZOATE),
    "e213": ("Calcium benzoate", MODERATE, _BENZOATE),
    "e220": ("Sulphur dioxide", MODERATE, _SULPHITE),
    "e221": ("Sodium sulphite", MODERATE, _SULPHITE),
    "e222": ("Sodium bisulphite", MODERATE, _SULPHITE),
    "e223": ("Sodium metabisulphite", MODERATE, _SULPHITE),
    "e224": ("Potassium metabisulphite", MODERATE, _SULPHITE),
    "e226": ("Calcium sulphite", MODERATE, _SULPHITE),
    "e227": ("Calcium bisulphite", MODERATE, _SULPHITE),
    "e228": ("Potassium bisulphite", MODERATE, _SULPHITE),
    "e249": ("Potassium nitrite", HIGH, _NITRITE),
    "e250": ("Sodium nitrite", HIGH, _NITRITE),
    "e251": ("Sodium nitrate", HIGH, _NITRITE),
    "e252": ("Potassium nitrate", HIGH, _NITRITE),
    # antioxidants
    "e319": ("TBHQ", MODERATE, "Synthetic antioxidant; animal studies raised immune-system "
             "concerns and it is restricted in some countries."),
    "e320": ("BHA", HIGH, "Classified possibly carcinogenic to humans (IARC 2B) and a "
             "suspected endocrine disruptor."),
    "e321": ("BHT", MODERATE, "Synthetic antioxidant and suspected endocrine disruptor; "
             "EFSA lowered its acceptable daily intake."),
    "e385": ("Calcium disodium EDTA", LOW, "Binds minerals; safe at permitted levels."),
    # phosphates
    "e338": ("Phosphoric acid", MODERATE, _PHOSPHATE),
    "e339": ("Sodium phosphates", MODERATE, _PHOSPHATE),
    "e340": ("Potassium phosphates", MODERATE, _PHOSPHATE),
    "e341": ("Calcium phosphates", MODERATE, _PHOSPHATE),
    "e450": ("Diphosphates", MODERATE, _PHOSPHATE),
    "e451": ("Triphosphates", MODERATE, _PHOSPHATE),
    "e452": ("Polyphosphates", MODERATE, _PHOSPHATE),
    # thickeners / emulsifiers
    "e407": ("Carrageenan", MODERATE, "Linked to gut inflammation in animal studies; its "
             "degraded form is a possible carcinogen."),
    "e407a": ("Processed eucheuma seaweed", MODERATE, "Carrageenan-type thickener; linked "
              "to gut inflammation in animal studies."),
    "e433": ("Polysorbate 80", MODERATE, _EMULSIFIER),
    "e466": ("Carboxymethylcellulose", MODERATE, _EMULSIFIER),
    "e471": ("Mono- and diglycerides of fatty acids", MODERATE, "Can carry small amounts "
             "of trans fats; high emulsifier intake was associated with cardiovascular "
             "risk in the NutriNet-Santé cohort."),
    "e472e": ("DATEM", LOW, "Emulsifier; considered safe, some animal data on heart tissue."),
    "e481": ("Sodium stearoyl lactylate", LOW, "Emulsifier; considered safe at permitted levels."),
    "e1520": ("Propylene glycol", LOW, "Generally safe; can irritate in high amounts."),
    # aluminium compounds
    "e173": ("Aluminium", MODERATE, _ALUMINIUM),
    "e520": ("Aluminium sulphate", MODERATE, _ALUMINIUM),
    "e521": ("Aluminium sodium sulphate", MODERATE, _ALUMINIUM),
    "e523": ("Aluminium ammonium sulphate", MODERATE, _ALUMINIUM),
    "e541": ("Sodium aluminium phosphate", MODERATE, _ALUMINIUM),
    "e554": ("Sodium aluminium silicate", MODERATE, _ALUMINIUM),
    "e556": ("Calcium aluminium silicate", MODERATE, _ALUMINIUM),
    "e559": ("Aluminium silicate", MODERATE, _ALUMINIUM),
    # flavour enhancers
    "e621": ("Monosodium glutamate (MSG)", LOW, "Considered safe; some people report "
             "sensitivity. Often a marker of heavily seasoned processed food."),
    "e627": ("Disodium guanylate", LOW, "Flavour enhancer; avoid with gout."),
    "e631": ("Disodium inosinate", LOW, "Flavour enhancer; avoid with gout."),
    "e635": ("Disodium 5'-ribonucleotides", LOW, "Flavour enhancer; occasional itchy rash reported."),
    # sweeteners
    "e950": ("Acesulfame K", MODERATE, "Artificial sweetener; long-term effects on gut "
             "microbiota and metabolism are still debated."),
    "e951": ("Aspartame", MODERATE, "Classified possibly carcinogenic to humans (IARC 2B, "
             "2023), though WHO kept its acceptable daily intake unchanged."),
    "e952": ("Cyclamate", MODERATE, "Artificial sweetener banned in the US since 1969."),
    "e954": ("Saccharin", MODERATE, "Artificial sweetener; may alter gut microbiota."),
    "e955": ("Sucralose", MODERATE, "May alter gut microbiota; a 2023 study found a "
             "breakdown product (sucralose-6-acetate) genotoxic in vitro."),
    "e962": ("Aspartame-acesulfame salt", MODERATE, "Combination of aspartame and "
             "acesulfame K (see both)."),
    # other
    "e900": ("Dimethylpolysiloxane", LOW, "Anti-foaming agent; considered safe."),
    "e924": ("Potassium bromate", HIGH, "Possible human carcinogen (IARC 2B); banned in "
             "the EU, UK, Canada and others."),
}

# ingredient-level patterns: (key, name, level, reason, OFF tags, text regex)
INGREDIENTS = [
    ("trans-fat", "Hydrogenated fats", HIGH,
     "Partially hydrogenated oils are the main source of industrial trans fats, which "
     "raise LDL cholesterol; WHO calls for eliminating them.",
     {"hydrogenated-vegetable-oil", "hydrogenated-oil", "partially-hydrogenated-oil",
      "hydrogenated-fat", "partially-hydrogenated-vegetable-oil"},
     r"\bhydrogenated\b|\bhydrogéné|\bgehärtet"),
    ("palm-oil", "Palm oil", MODERATE,
     "Rich in saturated fat; refined palm oil carries process contaminants (glycidyl "
     "esters) that EFSA flagged as a health concern.",
     set(), r"\bpalm (?:oil|fat|kernel)|\bhuile de palme|\bpalmöl|\bpalmfett"),
    ("hfcs", "Glucose-fructose syrup", MODERATE,
     "Rapidly absorbed added sugar; high intake is tied to fatty liver and "
     "metabolic disease.",
     {"glucose-fructose-syrup", "high-fructose-corn-syrup", "fructose-glucose-syrup",
      "corn-syrup", "high-fructose-syrup"},
     r"high[- ]fructose corn syrup|glucose[- ]fructose syrup|fructose[- ]glucose syrup"
     r"|\bcorn syrup|sirop de glucose[- ]fructose"),
]

# text matches for sweeteners/additives listed by name instead of E-number
_NAMED_ADDITIVES = {
    "e951": r"\baspartame\b", "e955": r"\bsucralose\b", "e950": r"\bacesulfame",
    "e250": r"\bsodium nitrite\b", "e621": r"\bmonosodium glutamate\b|\bmsg\b",
    "e171": r"\btitanium dioxide\b", "e407": r"\bcarrageenan\b",
}


def base_code(tag: str) -> str:
    """'e322i' -> 'e322', 'e150d' stays (it's its own entry), 'e450iii' -> 'e450'."""
    tag = tag.lower().strip()
    if tag in ADDITIVES:
        return tag
    m = re.match(r"^(e\d{3,4}[a-z]?)(?:i{1,3}|iv|v|vi)?$", tag)
    if m and m.group(1) in ADDITIVES:
        return m.group(1)
    m = re.match(r"^(e\d{3,4})", tag)
    return m.group(1) if m else tag


def unique_additives(additives: list) -> list:
    """Dedupe sub-variants (e322 + e322i is one additive, not two)."""
    seen, out = set(), []
    for a in additives or []:
        b = base_code(a)
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def find_risks(product: dict) -> list:
    """Risky ingredients for a normalized product, worst first.
    Each: {"code", "name", "level", "reason"}."""
    found = {}
    text = (product.get("ingredients_text") or "").lower()

    codes = unique_additives(product.get("additives") or [])
    for code, pattern in _NAMED_ADDITIVES.items():
        if code not in codes and text and re.search(pattern, text):
            codes.append(code)
    for code in codes:
        if code in ADDITIVES:
            name, level, reason = ADDITIVES[code]
            found[code] = {"code": code.upper(), "name": name,
                           "level": level, "reason": reason}

    tags = set(product.get("ingredient_tags") or [])
    analysis = set(product.get("ingredients_analysis") or [])
    for key, name, level, reason, ing_tags, pattern in INGREDIENTS:
        hit = bool(tags & ing_tags) or (text and re.search(pattern, text))
        if key == "palm-oil":  # OFF's own analysis is the most reliable signal
            hit = hit or "palm-oil" in analysis
        if hit:
            found[key] = {"code": None, "name": name, "level": level, "reason": reason}

    order = {HIGH: 0, MODERATE: 1, LOW: 2}
    return sorted(found.values(), key=lambda r: order[r["level"]])
