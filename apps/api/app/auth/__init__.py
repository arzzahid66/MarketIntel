"""Auth provider registry."""

from __future__ import annotations

from functools import lru_cache

from app.auth.base import AuthError, AuthProvider
from app.auth.clerk import ClerkAuthProvider
from app.auth.local import LocalAuthProvider
from app.core.config import settings

_PROVIDERS: dict[str, type] = {
    LocalAuthProvider.name: LocalAuthProvider,
    ClerkAuthProvider.name: ClerkAuthProvider,
}


@lru_cache(maxsize=1)
def get_auth_provider() -> AuthProvider:
    provider_cls = _PROVIDERS.get(settings.auth_provider)
    if provider_cls is None:
        raise RuntimeError(f"Unknown AUTH_PROVIDER {settings.auth_provider!r}")
    return provider_cls()  # type: ignore[return-value]


__all__ = [
    "AuthError",
    "AuthProvider",
    "ClerkAuthProvider",
    "LocalAuthProvider",
    "get_auth_provider",
]
