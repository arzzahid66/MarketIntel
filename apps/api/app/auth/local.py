"""Built-in email + password provider. Development, test and CI only."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.base import AuthError
from app.core.security import TokenError, decode_token, verify_password
from app.models.user import User


class LocalAuthProvider:
    name = "local"
    supports_password_auth = True

    def user_from_bearer_token(self, db: Session, token: str) -> User:
        try:
            payload = decode_token(token, expected_type="access")
        except TokenError as exc:
            raise AuthError(str(exc)) from exc

        try:
            user_id = uuid.UUID(payload["sub"])
        except (ValueError, KeyError) as exc:
            raise AuthError("Token subject is not a user id") from exc

        user = db.get(User, user_id)
        if user is None:
            raise AuthError("User no longer exists")
        if not user.is_active:
            raise AuthError("User account is disabled")
        return user

    def authenticate_password(self, db: Session, email: str, password: str) -> User:
        """Constant-ish work regardless of whether the email exists."""
        user = db.scalars(select(User).where(User.email == email.lower().strip())).first()
        password_hash = user.password_hash if user else None

        if not verify_password(password, password_hash):
            raise AuthError("Incorrect email or password")
        assert user is not None  # noqa: S101 - verify_password fails closed on None
        if not user.is_active:
            raise AuthError("User account is disabled")
        return user
