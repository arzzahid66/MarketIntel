"""Phase 1 exit criterion: signup -> login -> protected page works."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.watchlist import Watchlist
from tests.conftest import VALID_PASSWORD, auth_headers, signup


def test_signup_then_login_then_protected_route(client: TestClient) -> None:
    tokens = signup(client, "someone@example.com")
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0

    login = client.post(
        "/auth/login", json={"email": "someone@example.com", "password": VALID_PASSWORD}
    )
    assert login.status_code == 200

    me = client.get("/auth/whoami", headers=auth_headers(login.json()))
    assert me.status_code == 200
    assert me.json()["email"] == "someone@example.com"


def test_protected_route_rejects_anonymous(client: TestClient) -> None:
    response = client.get("/auth/whoami")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_protected_route_rejects_garbage_token(client: TestClient) -> None:
    response = client.get("/auth/whoami", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_password_is_never_stored_in_clear(client: TestClient, db: Session) -> None:
    signup(client, "hash@example.com")
    user = db.scalars(select(User).where(User.email == "hash@example.com")).one()
    assert user.password_hash is not None
    assert VALID_PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$2b$")


def test_signup_creates_a_default_watchlist(client: TestClient, db: Session) -> None:
    signup(client, "watch@example.com")
    user = db.scalars(select(User).where(User.email == "watch@example.com")).one()
    watchlists = db.scalars(select(Watchlist).where(Watchlist.user_id == user.id)).all()
    assert len(watchlists) == 1
    assert watchlists[0].is_default is True


def test_duplicate_signup_is_rejected(client: TestClient) -> None:
    signup(client, "dupe@example.com")
    response = client.post(
        "/auth/signup", json={"email": "dupe@example.com", "password": VALID_PASSWORD}
    )
    assert response.status_code == 409


def test_email_is_normalised(client: TestClient) -> None:
    signup(client, "mixed@example.com")
    response = client.post(
        "/auth/login", json={"email": "  MIXED@Example.COM ", "password": VALID_PASSWORD}
    )
    assert response.status_code == 200


def test_wrong_password_is_rejected(client: TestClient) -> None:
    signup(client, "wrong@example.com")
    response = client.post(
        "/auth/login", json={"email": "wrong@example.com", "password": "definitely-not-it"}
    )
    assert response.status_code == 401


def test_login_for_unknown_email_says_the_same_thing(client: TestClient) -> None:
    """No account-existence oracle: unknown email and wrong password look alike."""
    signup(client, "known@example.com")
    unknown = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": VALID_PASSWORD}
    )
    wrong = client.post(
        "/auth/login", json={"email": "known@example.com", "password": "definitely-not-it"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


@pytest.mark.parametrize("password", ["short", "123456789"])
def test_weak_passwords_are_rejected(client: TestClient, password: str) -> None:
    response = client.post("/auth/signup", json={"email": "weak@example.com", "password": password})
    assert response.status_code == 422


def test_refresh_token_issues_a_new_access_token(client: TestClient) -> None:
    tokens = signup(client, "refresh@example.com")
    response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    new_access = response.json()["access_token"]
    protected = client.get("/auth/whoami", headers={"Authorization": f"Bearer {new_access}"})
    assert protected.status_code == 200


def test_access_token_is_not_accepted_as_a_refresh_token(client: TestClient) -> None:
    tokens = signup(client, "swap@example.com")
    response = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert response.status_code == 401


def test_refresh_token_is_not_accepted_as_an_access_token(client: TestClient) -> None:
    tokens = signup(client, "swap2@example.com")
    response = client.get(
        "/auth/whoami", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert response.status_code == 401


def test_deactivated_user_loses_access_immediately(client: TestClient, db: Session) -> None:
    """A held token must not outlive the account it belongs to."""
    tokens = signup(client, "banned@example.com")
    user = db.scalars(select(User).where(User.email == "banned@example.com")).one()
    user.is_active = False
    db.commit()

    assert client.get("/auth/whoami", headers=auth_headers(tokens)).status_code == 401


def test_token_carries_no_plan_claim(client: TestClient) -> None:
    """Non-negotiable rule: entitlements are never baked into a JWT."""
    import jwt

    tokens = signup(client, "claims@example.com")
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    assert set(claims) == {"sub", "typ", "iat", "exp", "jti"}
