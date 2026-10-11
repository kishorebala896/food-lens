"""Vercel entrypoint. vercel.json rewrites /api/* here; the FastAPI app in
main.py does the actual routing (its routes all live under /api)."""

import os
import sys

# the app's modules live at the repo root, one level up
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402,F401
