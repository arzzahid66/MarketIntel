"""The plan matrix is data, and access checks read it. These tests are the proof."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.plan import UNLIMITED, Plan, PlanFeature
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services import features as F
from app.services.entitlements import resolve_anonymous, resolve_for_user
from tests.conftest import auth_headers, signup

# --------------------------------------------------------------------------
# The matrix itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("plan_code", "refresh", "ticker_limit", "ai_per_day", "can_post"),
    [
        ("free", 300, 0, 5, False),
        ("plus", 60, 15, 50, True),
        ("pro", 15, UNLIMITED, UNLIMITED, True),
    ],
)
def test_seeded_matrix_matches_the_build_plan(
    db: Session, plan_code: str, refresh: int, ticker_limit: int, ai_per_day: int, can_post: bool
) -> None:
    plan = db.scalars(select(Plan).where(Plan.code == plan_code)).one()
    values = {f.feature_key: f.value for f in plan.features}
    assert int(values[F.REFRESH_INTERVAL_SECONDS]) == refresh
    assert int(values[F.CUSTOM_TICKER_LIMIT]) == ticker_limit
    assert int(values[F.AI_MESSAGES_PER_DAY]) == ai_per_day
    assert (values[F.CHAT_CAN_POST] == "true") is can_post


def test_every_plan_defines_every_feature_key(db: Session) -> None:
    """A plan missing a key would fail open or closed at random. Catch it here."""
    for plan in db.scalars(select(Plan)).all():
        keys = {f.feature_key for f in plan.features}
        missing = set(F.ALL_FEATURE_KEYS) - keys
        assert keys == set(F.ALL_FEATURE_KEYS), f"{plan.code} is missing {missing}"


def test_anonymous_visitors_get_the_free_plan(db: Session) -> None:
    entitlements = resolve_anonymous(db)
    assert entitlements.plan_code == "free"
    assert entitlements.limit(F.REFRESH_INTERVAL_SECONDS) == 300


# --------------------------------------------------------------------------
# Resolution rules
# --------------------------------------------------------------------------


def test_user_without_a_subscription_is_free(client: TestClient, free_user: dict) -> None:
    body = client.get("/me", headers=auth_headers(free_user)).json()
    assert body["entitlements"]["plan_code"] == "free"
    assert body["entitlements"]["subscription_status"] is None


def test_active_subscription_grants_its_plan(client: TestClient, plus_user: dict) -> None:
    body = client.get("/me", headers=auth_headers(plus_user)).json()
    assert body["entitlements"]["plan_code"] == "plus"
    assert body["entitlements"]["subscription_status"] == "active"
    assert body["entitlements"]["features"][F.CUSTOM_TICKER_LIMIT] == 15


@pytest.mark.parametrize(
    "status",
    [
        SubscriptionStatus.CANCELED,
        SubscriptionStatus.PAST_DUE,
        SubscriptionStatus.INCOMPLETE,
    ],
)
def test_non_granting_subscription_falls_back_to_free(
    client: TestClient, db: Session, status: SubscriptionStatus
) -> None:
    tokens = signup(client, "lapsed@example.com")
    user = db.scalars(select(User).where(User.email == "lapsed@example.com")).one()
    plan = db.scalars(select(Plan).where(Plan.code == "pro")).one()
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status=status))
    db.commit()

    body = client.get("/me", headers=auth_headers(tokens)).json()
    assert body["entitlements"]["plan_code"] == "free"


def test_trialing_counts_as_access(client: TestClient, db: Session) -> None:
    tokens = signup(client, "trial@example.com")
    user = db.scalars(select(User).where(User.email == "trial@example.com")).one()
    plan = db.scalars(select(Plan).where(Plan.code == "plus")).one()
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status=SubscriptionStatus.TRIALING))
    db.commit()

    body = client.get("/me", headers=auth_headers(tokens)).json()
    assert body["entitlements"]["plan_code"] == "plus"


def test_downgrade_takes_effect_on_the_next_request_with_the_same_token(
    client: TestClient, db: Session, plus_user: dict
) -> None:
    """The stale-token case the build plan calls out. The token does not change;
    the answer does, because entitlements come from the database."""
    assert client.get("/demo/gated/chat-post", headers=auth_headers(plus_user)).status_code == 200

    subscription = db.scalars(select(Subscription)).one()
    subscription.status = SubscriptionStatus.CANCELED
    db.commit()

    assert client.get("/demo/gated/chat-post", headers=auth_headers(plus_user)).status_code == 402


# --------------------------------------------------------------------------
# Gating
# --------------------------------------------------------------------------


def test_free_user_hitting_a_paid_route_gets_402_with_upgrade_context(
    client: TestClient, free_user: dict
) -> None:
    response = client.get("/demo/gated/chat-post", headers=auth_headers(free_user))
    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["error"] == "upgrade_required"
    assert detail["feature"] == F.CHAT_CAN_POST
    assert detail["current_plan"] == "free"


def test_anonymous_user_hitting_a_paid_route_gets_402(client: TestClient) -> None:
    assert client.get("/demo/gated/chat-post").status_code == 402


def test_paid_user_passes_the_gate(client: TestClient, pro_user: dict) -> None:
    assert client.get("/demo/gated/chat-post", headers=auth_headers(pro_user)).status_code == 200


def test_refresh_interval_differs_by_plan(
    client: TestClient, free_user: dict, plus_user: dict, pro_user: dict
) -> None:
    def interval(tokens: dict | None) -> int:
        headers = auth_headers(tokens) if tokens else {}
        return client.get("/demo/gated/refresh-interval", headers=headers).json()[
            "refresh_interval_seconds"
        ]

    assert interval(None) == 300
    assert interval(free_user) == 300
    assert interval(plus_user) == 60
    assert interval(pro_user) == 15


# --------------------------------------------------------------------------
# Changing limits without a deploy
# --------------------------------------------------------------------------


def test_changing_a_db_row_changes_behaviour_with_no_code_change(
    client: TestClient, db: Session, free_user: dict
) -> None:
    """The whole reason the matrix is data. Flip one row, the gate opens."""
    assert client.get("/demo/gated/chat-post", headers=auth_headers(free_user)).status_code == 402

    feature = db.scalars(
        select(PlanFeature)
        .join(Plan)
        .where(Plan.code == "free", PlanFeature.feature_key == F.CHAT_CAN_POST)
    ).one()
    feature.value = "true"
    db.commit()

    try:
        assert (
            client.get("/demo/gated/chat-post", headers=auth_headers(free_user)).status_code == 200
        )
    finally:
        feature.value = "false"
        db.commit()


def test_unlimited_is_expressed_as_minus_one(
    client: TestClient, db: Session, pro_user: dict
) -> None:
    user = db.scalars(select(User).where(User.email == "pro@example.com")).one()
    entitlements = resolve_for_user(db, user)
    assert entitlements.is_unlimited(F.CUSTOM_TICKER_LIMIT)
    assert entitlements.within_limit(F.CUSTOM_TICKER_LIMIT, current_count=10_000)


def test_within_limit_enforces_a_finite_ceiling(
    db: Session, client: TestClient, plus_user: dict
) -> None:
    user = db.scalars(select(User).where(User.email == "plus@example.com")).one()
    entitlements = resolve_for_user(db, user)
    assert entitlements.within_limit(F.CUSTOM_TICKER_LIMIT, current_count=14)
    assert not entitlements.within_limit(F.CUSTOM_TICKER_LIMIT, current_count=15)


def test_feature_keys_endpoint_lists_the_whole_matrix(client: TestClient) -> None:
    assert set(client.get("/entitlements/keys").json()) == set(F.ALL_FEATURE_KEYS)
