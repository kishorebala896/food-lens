"""food-lens API. JSON in/out; the UI is the static PWA in public/.

Locally `uvicorn main:app --reload` serves both (API + public/ at /).
On Vercel, public/ goes to the CDN and api/index.py wraps this same app.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from alternatives import find_alternatives
from explain import LLMExplainer, default_explainer, explain
from off_client import OFFError, clean_barcode, lookup, search
from risks import find_risks
from score import nutrient_table, score_product

app = FastAPI(title="food-lens", docs_url="/api/docs", openapi_url="/api/openapi.json")

# products barely change; let Vercel's CDN (and the browser) hold on to answers
# so we don't hammer Open Food Facts' rate limits
CACHE_LONG = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"
CACHE_SHORT = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"


def _json(data: dict, cache: Optional[str] = None) -> JSONResponse:
    headers = {"Cache-Control": cache} if cache else {}
    return JSONResponse(data, headers=headers)


def _upstream_down(e: Exception) -> HTTPException:
    return HTTPException(502, "Open Food Facts is not responding right now — try again "
                              "in a minute.")


def _card(p: dict) -> dict:
    """Compact product row for lists (search results)."""
    s = score_product(p, find_risks(p))
    return {"barcode": p["barcode"], "name": p["name"], "brands": p["brands"],
            "quantity": p["quantity"], "image_url": p["image_small_url"],
            "nutriscore_grade": p["nutriscore_grade"],
            "score": s["score"], "band": s["band"], "color": s["color"]}


@app.get("/api/health")
def health():
    return {"ok": True,
            "explainer": "llm" if isinstance(default_explainer(), LLMExplainer) else "template"}


@app.get("/api/product/{barcode}")
def product(barcode: str):
    code = clean_barcode(barcode)
    if not 6 <= len(code) <= 14:
        raise HTTPException(400, "That doesn't look like a barcode (expect 8–14 digits).")
    try:
        p = lookup(code)
    except OFFError as e:
        raise _upstream_down(e)
    if p is None:
        raise HTTPException(404, f"Barcode {code} isn't in Open Food Facts yet — "
                                 "crowdsourced DB, gaps happen. Try searching by name.")

    risks = find_risks(p)
    result = score_product(p, risks)
    text, explainer_name = explain(p, result, risks)
    public = {k: v for k, v in p.items()
              if k not in ("ingredient_tags", "ingredients_analysis", "nutriments")}
    return _json({
        "product": public,
        "score": result,
        "risks": risks,
        "nutrients": nutrient_table(p),
        "explanation": text,
        "explainer": explainer_name,
    }, CACHE_LONG)


@app.get("/api/alternatives/{barcode}")
def alternatives(barcode: str):
    try:
        p = lookup(clean_barcode(barcode))
    except OFFError as e:
        raise _upstream_down(e)
    if p is None:
        raise HTTPException(404, "Unknown barcode.")
    s = score_product(p, find_risks(p))
    return _json(find_alternatives(p, s["score"]), CACHE_LONG)


@app.get("/api/search")
def search_products(q: str = Query(..., min_length=2, max_length=100),
                    page: int = Query(1, ge=1, le=50)):
    try:
        res = search(q.strip(), page=page)
    except OFFError as e:
        raise _upstream_down(e)
    return _json({"query": q, "page": res["page"], "page_count": res["page_count"],
                  "results": [_card(p) for p in res["products"]]}, CACHE_SHORT)


# local dev convenience: serve the PWA from the same origin. On Vercel the CDN
# serves public/ and only /api/* is routed to this app, so the mount is inert.
_PUBLIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
if os.path.isdir(_PUBLIC):
    app.mount("/", StaticFiles(directory=_PUBLIC, html=True), name="public")
