"""The user's own record plus their resolved entitlements.

The web app calls this once per page load and uses `entitlements.features` to
decide what to render and where to show upgrade prompts. It is a *hint* - the
server re-checks on every gated call.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.auth.deps import CurrentEntitlements, CurrentUser, DbSession
from app.schemas.common import EntitlementsOut, MeResponse, UserOut
from app.services import features as F
from app.services.entitlements import Entitlements, resolve_anonymous

router = APIRouter(tags=["me"])


def _to_out(e: Entitlements) -> EntitlementsOut:
    return EntitlementsOut(
        plan_code=e.plan_code,
        plan_name=e.plan_name,
        subscription_status=e.subscription_status,
        features=e.values,
    )


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, entitlements: CurrentEntitlements) -> MeResponse:
    return MeResponse(user=UserOut.model_validate(user), entitlements=_to_out(entitlements))


@router.get("/entitlements", response_model=EntitlementsOut)
def entitlements(entitlements: CurrentEntitlements) -> EntitlementsOut:
    """Works logged out too, returning the free tier - the free dashboard needs
    a refresh interval before anyone has signed up."""
    return _to_out(entitlements)


@router.get("/entitlements/public", response_model=EntitlementsOut)
def public_entitlements(db: DbSession) -> EntitlementsOut:
    """Explicitly anonymous, for cacheable server-rendered public pages."""
    return _to_out(resolve_anonymous(db))


@router.get("/entitlements/keys", response_model=list[str])
def entitlement_keys() -> list[str]:
    """Every feature key the codebase knows about. Keeps the web app honest."""
    return list(F.ALL_FEATURE_KEYS)
