# food-lens

Barcode in, health score out — with an actual explanation of the *why*.

I kept wondering how much of those food-scanning apps is real engineering vs. a product database with a coat of paint. So I built the core loop myself one evening: barcode → Open Food Facts lookup → deterministic health score → plain-English explanation.

The part I'd defend in an interview: I didn't build a database. Open Food Facts has 3M+ products, free, no key — building my own would've been pure ego. The actual work is what happens *after* the lookup, and the deliberate split in this repo: **fixed rules do the scoring, the LLM only writes the explanation.** Reproducible math, swappable prose. Each belongs where it belongs.

Loosely inspired by Yuka-style scanners. (One line, as promised.)

## What it does

It's a PWA — deploy it, open it on your phone, "Add to Home Screen", and it behaves like an app.

1. **Scan** a barcode with the live camera (native `BarcodeDetector` on Android Chrome, ZXing fallback on iPhone), **or search** by keyword and pick from the matches — every search result already shows its score.
2. The result screen shows:
   - the **health score** (0–100) with Nutri-Score / NOVA badges
   - **risky ingredients** — flagged additives (E-numbers) and ingredients like palm oil or hydrogenated fats, each with a high / moderate / low level and a one-line reason
   - **why this score** — plain-English explanation plus the exact point-by-point breakdown
   - **healthier alternatives** from the same category that beat it by 10+ points
   - nutrition per 100g with traffic-light levels, and the ingredient list
3. Recent scans are kept on the device, and results you've already looked at still open offline.

## How it runs

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://localhost:8000. The same process serves the API (`/api/*`) and the PWA (`public/`). Try `3017620422003`. That's Nutella. Spoiler: it does not go well.

The camera needs HTTPS — `localhost` counts, but your phone hitting your laptop's LAN IP doesn't. For testing on a real phone, deploy (below) or use a tunnel.

No keys needed — the default explainer is a template renderer that turns the score breakdown into sentences, and it's honestly decent. If you want LLM-written explanations, set `LLM_API_BASE` / `LLM_API_KEY` (any OpenAI-compatible endpoint, optionally `LLM_MODEL`) and it'll pick that up automatically. If the LLM call fails, it quietly falls back to the template.

There's also a CLI if you don't want the server: `python demo.py 4000417675217`.

## Deploying to Vercel

1. Push the repo to GitHub and import it in Vercel (or run `vercel` from the repo root).
2. No settings to change — `vercel.json` pins it: `public/` is served as static files, `api/index.py` runs the FastAPI app as a Python function, and `/api/*` is rewritten to it.
3. Optional: add `LLM_API_BASE` / `LLM_API_KEY` under Project → Settings → Environment Variables.
4. Open the URL on your phone → **Android/Chrome:** tap *Install* on the home screen banner (or ⋮ → *Install app*). **iPhone/Safari:** Share → *Add to Home Screen*.

API responses carry `s-maxage` cache headers, so Vercel's CDN absorbs repeat lookups instead of burning Open Food Facts' rate limits.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/product/{barcode}` | product, score + factor breakdown, risky ingredients, nutrients, explanation |
| `GET /api/alternatives/{barcode}` | up to 6 better-scoring products from the same category |
| `GET /api/search?q=…&page=…` | keyword matches, each already scored |
| `GET /api/health` | which explainer is active |

## What surprised me

How half-empty the crowdsourced data is. Missing nutriments are the norm, not the exception — every single field access needed a guard, and the scorer has to say "score may be optimistic" instead of pretending. Also, Open Food Facts 403s you outright if your User-Agent looks like a bot. Ask me how I know.

## Rough edges (honest ones)

- Barcode scanning is browser-side now (no more `pyzbar`), but cheap phone cameras still struggle with tiny or curved barcodes — the scanner has a "type the digits" field for exactly that.
- Alternatives are only as good as OFF's category tags. Popular products come first, and anything with missing nutrition data is skipped rather than guessed at.
- The risky-ingredient table (`risks.py`) is short and curated, not exhaustive. Unlisted additives still cost a point each.
- The scoring rubric is mine — reasonable, Nutri-Score-informed, but I'm not a dietitian. It's in one readable function (`score.py`) so you can argue with it.
- No OCR yet, so ingredient lists come from the API or not at all. That's next.

## TODO

- Label OCR from photos (ingredient lists straight off the package)
- Ingredient-name normalization across brands/languages (the unsexy hard part)
- RAG over a curated additives/nutrition knowledge base so explanations cite sources instead of sounding confident
- A dietitian-labeled eval set — "87% agreement" beats "looks right to me"
- Cosmetics via Open Beauty Facts
- Personal filters (vegan, allergens) that change what counts as "risky"

## Layout

- `off_client.py` — Open Food Facts lookup + search (User-Agent, retries, guards everywhere)
- `score.py` — deterministic 0–100 scoring + per-factor breakdown + nutrient levels
- `risks.py` — curated risky additives/ingredients, each with a level and a reason
- `alternatives.py` — same-category, better-scoring suggestions (same rubric)
- `explain.py` — `Explainer` interface: `TemplateExplainer` default, `LLMExplainer` hook
- `main.py` — FastAPI JSON API (also serves `public/` locally)
- `api/index.py` — Vercel entrypoint wrapping `main.app`
- `public/` — the PWA: `app.js` (screens + routing), `scanner.js` (camera), `sw.js` (offline), manifest, icons. No build step.
- `demo.py` — CLI version of the pipeline
