"""Explainer interface: deterministic score in, plain-English "why" out.

TemplateExplainer is the default — no keys, works out of the box.
LLMExplainer is the optional upgrade: bring your own OpenAI-compatible
endpoint via LLM_API_BASE / LLM_API_KEY. Same interface, swappable.

The point of the split: scoring is rules (reproducible, testable, arguable),
explaining is language (where the LLM actually earns its keep).
"""

from __future__ import annotations

import json
import os
import urllib.request


class Explainer:
    def explain(self, product: dict, score_result: dict) -> str:
        raise NotImplementedError


class TemplateExplainer(Explainer):
    """No-model fallback. Renders the factor breakdown as sentences.
    Honestly decent — the breakdown already carries the content."""

    def explain(self, product: dict, score_result: dict) -> str:
        name = product.get("name", "this product")
        score = score_result["score"]
        band = score_result["band"]
        factors = [f for f in score_result["factors"] if f["points"] != 0]

        negs = sorted([f for f in factors if f["points"] < 0],
                      key=lambda f: f["points"])
        poss = sorted([f for f in factors if f["points"] > 0],
                      key=lambda f: -f["points"])

        bits = [f"{name} scores {score}/100 — {band}."]
        if negs:
            worst = negs[0]
            bits.append(
                f"The biggest hit ({worst['points']:+g} points) is "
                f"{worst['label'].lower()}: {worst['detail']}.")
            for f in negs[1:3]:
                bits.append(f"Also dragging it down: {f['label'].lower()} "
                            f"({f['points']:+g}) — {f['detail']}.")
        if poss:
            p = poss[0]
            bits.append(f"On the plus side: {p['detail']}.")
        if not negs and not poss:
            bits.append("Not enough nutrition data reported to say much — "
                        "crowdsourced databases are patchy like that.")
        missing = [f for f in score_result["factors"]
                   if f["label"] == "Missing data"]
        if missing:
            bits.append("One caveat: " + missing[0]["detail"] + ".")
        return " ".join(bits)


class LLMExplainer(Explainer):
    """Calls any OpenAI-compatible chat endpoint. Bring your own key —
    the demo runs fine without this."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None):
        self.base_url = (base_url or os.environ.get("LLM_API_BASE", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
        if not self.base_url or not self.api_key:
            raise ValueError("LLM_API_BASE and LLM_API_KEY must be set")

    def explain(self, product: dict, score_result: dict) -> str:
        prompt = (
            "You are explaining a packaged-food health score to a shopper. "
            "Be conversational and specific; cite the numbers given. Do not "
            "invent nutrition facts beyond what's provided. Keep it under 120 words.\n\n"
            f"Product: {product.get('name')} "
            f"({', '.join(product.get('brands', []))})\n"
            f"Score: {score_result['score']}/100 ({score_result['band']})\n"
            "Factor breakdown:\n"
            + "\n".join(f"- {f['label']}: {f['points']:+g} pts — {f['detail']}"
                        for f in score_result["factors"])
        )
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 250,
            "temperature": 0.4,
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"].strip()


def default_explainer() -> Explainer:
    """LLM if configured, template otherwise. UI shows which one is active."""
    try:
        return LLMExplainer()
    except ValueError:
        return TemplateExplainer()
