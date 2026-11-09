"""A worked example of `require_feature`, and the fixture the Phase 1 test suite
uses to prove a free user gets 402 while a Plus user gets 200.

Delete this module in Phase 5. The real gated routes (chat, AI analyst, extended
markets) arrive in Phases 4-5 and must use the same dependency.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.deps import CurrentEntitlements, require_feature
from app.services import features as F
from app.services.entitlements import Entitlements

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/gated/chat-post")
def gated_chat_post(
    _: Annotated[Entitlements, Depends(require_feature(F.CHAT_CAN_POST))],
) -> dict[str, str]:
    """Free = 402 upgrade_required, Plus/Pro = 200."""
    return {"result": "you may post in chatrooms"}


@router.get("/gated/refresh-interval")
def refresh_interval(entitlements: CurrentEntitlements) -> dict[str, int | str]:
    """Ungated but plan-shaped: every tier gets an answer, a better one if paid."""
    return {
        "plan": entitlements.plan_code,
        "refresh_interval_seconds": entitlements.limit(F.REFRESH_INTERVAL_SECONDS),
        "custom_ticker_limit": entitlements.limit(F.CUSTOM_TICKER_LIMIT),
    }
