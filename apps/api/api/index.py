"""Vercel entry point for the FastAPI service.

Vercel's Python runtime routes every request to the ASGI callable `app` in this
module (see ../vercel.json). The file is only an adapter - all behaviour lives
in `apps/api/app`.

**This lives inside `apps/api`, and that placement is load-bearing.** Vercel
reads `vercel.json` from the *repository root*, not from each project's Root
Directory. With the API's config at the repo root it was also applied to the
Next.js project built from `apps/web`, whose build then ran no install, emitted
no files and 404'd on every path. Giving each project its own directory with
its own `vercel.json` is what keeps the two from configuring each other.

Two things differ from running under uvicorn, both consequences of serverless:

  * **No start command**, so migrations and the seed do not run on deploy. They
    are applied out of band - see docs/DEPLOYMENT.md. A schema change means
    running `alembic upgrade head` yourself *before* shipping code that needs it.
  * **No resident process**, so `GET /market/stream` cannot hold an SSE
    connection open. The web app already falls back to polling, which on this
    host is the real transport rather than the fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The directory holding the `app` package - i.e. apps/api, this file's
# grandparent. Prepended so the real package wins over any same-named module
# that happens to land in the function bundle.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

from app.main import app  # noqa: E402  (import must follow the sys.path edit)

__all__ = ["app"]
