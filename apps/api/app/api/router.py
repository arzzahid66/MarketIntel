from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    analyst,
    auth,
    chat,
    extended,
    feed,
    gated_demo,
    health,
    market,
    me,
    plans,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(plans.router)
api_router.include_router(market.router)
api_router.include_router(extended.router)
api_router.include_router(feed.router)
api_router.include_router(analyst.router)
api_router.include_router(chat.router)

# `/demo/gated/*` exists to exercise `require_feature` against a route with no
# product behaviour of its own, and nine entitlement tests depend on it -
# including the downgrade guard for rule 2. Deleting it, as Phase 5 originally
# planned, would delete the coverage for the single most security-critical
# property in the app. So it stays in the codebase and stays out of anything
# deployed: nobody with the URL sees a /demo namespace, and the tests keep
# their subject. Staging is excluded too - a staging URL is still a URL someone
# can find.
if settings.environment in ("development", "test"):
    api_router.include_router(gated_demo.router)
