"""Clerk provider: verify Clerk-issued JWTs against Clerk's JWKS.

Staging and production run on this. It is wired but inert until CLERK_JWKS_URL
and CLERK_ISSUER are set, so Phase 1 ships without blocking on the client's
Clerk account.

Users are provisioned just-in-time on first successful token verification:
Clerk owns the identity, we own the `users` row that subscriptions hang off.
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.base import AuthError
from app.core.config import settings
from app.models.user import User


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    if not settings.clerk_jwks_url:
        raise AuthError("CLERK_JWKS_URL is not configured")
    # PyJWKClient caches keys in-process and refetches on unknown kid (key rotation).
    return PyJWKClient(settings.clerk_jwks_url, cache_keys=True)


class ClerkAuthProvider:
    name = "clerk"
    supports_password_auth = False

    def user_from_bearer_token(self, db: Session, token: str) -> User:
        try:
            signing_key = _jwk_client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=settings.clerk_issuer or None,
                options={"require": ["exp", "sub"]},
            )
        except AuthError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthError(f"Clerk token rejected: {exc}") from exc

        external_id = claims.get("sub")
        email = (claims.get("email") or "").lower().strip()
        if not external_id:
            raise AuthError("Clerk token has no subject")

        user = db.scalars(select(User).where(User.external_auth_id == external_id)).first()

        # Link an existing local-era row by email before creating a duplicate.
        if user is None and email:
            user = db.scalars(select(User).where(User.email == email)).first()
            if user is not None:
                user.external_auth_id = external_id

        if user is None:
            if not email:
                raise AuthError("Clerk token has no email; cannot provision a user")
            user = User(
                email=email,
                external_auth_id=external_id,
                display_name=claims.get("name") or claims.get("first_name"),
            )
            db.add(user)

        db.commit()
        db.refresh(user)

        if not user.is_active:
            raise AuthError("User account is disabled")
        return user
