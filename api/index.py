"""Vercel entry point for the FastAPI service.

Vercel's Python runtime looks for an ASGI callable named `app` in a module
under `api/`, and routes every request to it (see vercel.json). This file is
only an adapter - all behaviour lives in `apps/api/app`.

**`apps/api` is put on the import path here** rather than installed, because
Vercel installs from a flat `requirements.txt` at the project root and does not
run `pip install -e ./apps/api`. The package is the shared domain layer and is
imported, not vendored, so there is still exactly one copy of the models.

Two things differ from running under uvicorn, and both are consequences of
serverless, not of this file:

  * **No start command**, so migrations and the seed do not run on deploy. They
    are applied out of band - see docs/DEPLOYMENT.md. A schema change means
    running `alembic upgrade head` against the database yourself *before*
    shipping the code that depends on it.
  * **No resident process**, so `GET /market/stream` cannot hold an SSE
    connection open for long. The web app already falls back to polling, which
    on this host is the real transport rather than the fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path

# apps/api, relative to this file. Prepended so the real package wins over any
# same-named module that happens to sit in the function bundle.
_API_ROOT = Path(__file__).resolve().parent.parent / "apps" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.main import app  # noqa: E402  (import must follow the sys.path edit)

__all__ = ["app"]
