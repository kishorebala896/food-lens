"""food-lens web app. One page: barcode in, score + explanation out."""

from __future__ import annotations

import io
import os

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from off_client import lookup
from score import score_product
from explain import default_explainer, LLMExplainer, TemplateExplainer

app = FastAPI(title="food-lens")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def decode_barcode_from_photo(data: bytes) -> str | None:
    """Best-effort barcode decode. pyzbar needs the zbar system lib, which
    most machines don't have — so this is optional, never a hard dependency."""
    try:
        from pyzbar.pyzbar import decode
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        codes = decode(img)
        return codes[0].data.decode("utf-8", errors="ignore") if codes else None
    except Exception:
        return None


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "result": None, "error": None,
        "llm_active": isinstance(default_explainer(), LLMExplainer),
    })


@app.post("/scan", response_class=HTMLResponse)
async def scan(request: Request, barcode: str = Form(""),
               photo: UploadFile | None = File(None)):
    error = None
    code = (barcode or "").strip()

    if photo is not None and photo.filename:
        data = await photo.read()
        decoded = decode_barcode_from_photo(data)
        if decoded:
            code = decoded
        elif not code:
            error = ("couldn't read a barcode from that photo — "
                     "type the digits in manually")

    product = lookup(code) if code and not error else None
    if code and not error and product is None:
        error = (f"barcode {code} isn't in Open Food Facts yet — "
                 "crowdsourced DB, gaps happen")

    result = None
    explanation = None
    if product:
        result = score_product(product["nutriments"], product["nova_group"],
                               product["additives"])
        explainer = default_explainer()
        explanation = explainer.explain(product, result)

    return templates.TemplateResponse(request, "index.html", {
        "result": {"product": product, "score": result,
                   "explanation": explanation, "barcode": code} if product else None,
        "error": error,
        "barcode": code,
        "llm_active": isinstance(default_explainer(), LLMExplainer),
    })
