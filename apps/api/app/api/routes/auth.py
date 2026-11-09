"""Signup / login / refresh for the local auth provider.

Under AUTH_PROVIDER=clerk these routes return 404: Clerk owns the flow and the
frontend talks to Clerk directly, then sends us its JWT.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth import AuthError, get_auth_provider
from app.auth.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import TokenError, create_token, decode_token, hash_password
from app.models.user import User
from app.models.watchlist import Watchlist
from app.schemas.auth import LoginRequest, RefreshRequest, SignupRequest, TokenPair
from app.schemas.common import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def _guard_password_auth() -> None:
    if not get_auth_provider().supports_password_auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Password auth is not enabled (AUTH_PROVIDER={settings.auth_provider})",
        )


def _token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_token(str(user.id), "access"),
        refresh_token=create_token(str(user.id), "refresh"),
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )


@router.post("/signup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: DbSession) -> TokenPair:
    _guard_password_auth()

    existing = db.scalars(select(User).where(User.email == payload.email)).first()
    if existing is not None:
        # Same wording as a failed login so this endpoint is not an account oracle.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email cannot be registered",
        )

    user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()

    # Every user gets a default dashboard now; Phase 4 fills it with custom tickers.
    db.add(Watchlist(user_id=user.id, name="My dashboard", is_default=True))
    db.commit()
    db.refresh(user)

    log.info("user_signed_up", user_id=str(user.id))
    return _token_pair(user)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: DbSession) -> TokenPair:
    _guard_password_auth()
    provider = get_auth_provider()

    try:
        user = provider.authenticate_password(db, payload.email, payload.password)  # type: ignore[attr-defined]
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user.last_login_at = datetime.now(UTC)
    db.commit()

    log.info("user_logged_in", user_id=str(user.id))
    return _token_pair(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    _guard_password_auth()
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    import uuid

    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User unavailable")
    return _token_pair(user)


@router.get("/whoami", response_model=UserOut)
def whoami(user: CurrentUser) -> User:
    """Cheapest possible protected route - used by the web app's route guard."""
    return user
