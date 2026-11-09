"""Auth provider interface.

The build plan says buy auth rather than build it, and staging/production do
exactly that via Clerk. But a project cannot have its test suite, its CI, and
its local dev loop depend on a third-party account being provisioned, so auth
sits behind an interface with two implementations:

    local  - email + password, bcrypt, HS256 JWT. Dev, test and CI only;
             `Settings.assert_production_safe()` refuses to boot production on it.
    clerk  - verifies Clerk-issued JWTs against Clerk's JWKS. No password ever
             touches our database.

Swapping is the AUTH_PROVIDER env var. Neither implementation is allowed to
return entitlements: those always come from the subscriptions table.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.models.user import User


class AuthError(Exception):
    """Credential or token rejected."""


@runtime_checkable
class AuthProvider(Protocol):
    #: Value of AUTH_PROVIDER that selects this implementation.
    name: str

    #: Whether /auth/signup and /auth/login are mounted.
    supports_password_auth: bool

    def user_from_bearer_token(self, db: Session, token: str) -> User:
        """Resolve a bearer token to a User row, or raise AuthError."""
        ...
