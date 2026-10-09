# food-lens

Barcode in, health score out — with an actual explanation of the *why*.

I kept wondering how much of those food-scanning apps is real engineering vs. a product database with a coat of paint. So I built the core loop myself one evening: barcode → Open Food Facts lookup → deterministic health score → plain-English explanation.

The part I'd defend in an interview: I didn't build a database. Open Food Facts has 3M+ products, free, no key — building my own would've been pure ego. The actual work is what happens *after* the lookup, and the deliberate split in this repo: **fixed rules do the scoring, the LLM only writes the explanation.** Reproducible math, swappable prose. Each belongs where it belongs.

Loosely inspired by Yuka-style scanners. (One line, as promised.)

## How it runs

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open http://localhost:8000, type a barcode (or snap one — photo decode is best-effort), and try `3017620422003`. That's Nutella. Spoiler: it does not go well.

No keys needed — the default explainer is a template renderer that turns the score breakdown into sentences, and it's honestly decent. If you want LLM-written explanations, set `LLM_API_BASE` / `LLM_API_KEY` (any OpenAI-compatible endpoint) and it'll pick that up automatically.

There's also a CLI if you don't want the server: `python demo.py 4000417675217`.

## What surprised me

How half-empty the crowdsourced data is. Missing nutriments are the norm, not the exception — every single field access needed a guard, and the scorer has to say "score may be optimistic" instead of pretending. Also, Open Food Facts 403s you outright if your User-Agent looks like a bot. Ask me how I know.

## Rough edges (honest ones)

- Photo barcode decoding is best-effort. `pyzbar` needs the zbar system lib most laptops don't have, so there's always a manual barcode field as the real path.
- The scoring rubric is mine — reasonable, Nutri-Score-informed, but I'm not a dietitian. It's in one readable function (`score.py`) so you can argue with it.
- No OCR yet, so ingredient lists come from the API or not at all. That's next.

## TODO

- Label OCR from photos (ingredient lists straight off the package)
- Ingredient-name normalization across brands/languages (the unsexy hard part)
- RAG over a curated additives/nutrition knowledge base so explanations cite sources instead of sounding confident
- A dietitian-labeled eval set — "87% agreement" beats "looks right to me"
- Cosmetics via Open Beauty Facts
- Scan history

## Layout

- `off_client.py` — Open Food Facts lookup (User-Agent, retries, guards everywhere)
- `score.py` — deterministic 0–100 scoring + per-factor breakdown
- `explain.py` — `Explainer` interface: `TemplateExplainer` default, `LLMExplainer` hook
- `main.py` — FastAPI app, one page
- `templates/index.html` — the whole UI, no build step
- `demo.py` — CLI version of the pipeline
