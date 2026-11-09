"""FastAPI auth + entitlement dependencies.

`require_feature` is the single gate every paid route will use from Phase 4
onwards. It exists now so no feature ever gets built against an ad-hoc check.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import AuthError, get_auth_provider
from app.db.session import get_db
from app.models.user import User
from app.services import entitlements as ent

_bearer = HTTPBearer(auto_error=False, description="Access token")
_optional_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Not authenticated")
    try:
        return get_auth_provider().user_from_bearer_token(db, credentials.credentials)
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc


def get_optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)] = None,
) -> User | None:
    """For pages that render for anyone but richer when signed in."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        return get_auth_provider().user_from_bearer_token(db, credentials.credentials)
    except AuthError:
        return None


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def get_entitlements(db: DbSession, user: OptionalUser) -> ent.Entitlements:
    """Resolved per request, from the database. Never from a token claim."""
    if user is None:
        return ent.resolve_anonymous(db)
    return ent.resolve_for_user(db, user)


CurrentEntitlements = Annotated[ent.Entitlements, Depends(get_entitlements)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def require_feature(feature_key: str) -> Callable[..., ent.Entitlements]:
    """Dependency factory gating a route on one feature key.

    Returns 402 rather than 403: the user is identified and permitted to exist
    here, they just need a higher plan. The client turns 402 into an upgrade
    prompt instead of an error toast.
    """

    def _dependency(request: Request, entitlements: CurrentEntitlements) -> ent.Entitlements:
        if not entitlements.allows(feature_key):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "upgrade_required",
                    "feature": feature_key,
                    "current_plan": entitlements.plan_code,
                    "path": request.url.path,
                },
            )
        return entitlements

    return _dependency
