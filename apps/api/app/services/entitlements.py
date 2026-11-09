"""Server-side entitlement resolution.

One function answers "what may this user do?", by reading the `subscriptions`
row and its plan's features. Every gated route goes through this. Nothing here
reads a token claim.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.plan import UNLIMITED, Plan, ValueType
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services import features as F

FeatureValue = bool | int | str


class EntitlementError(RuntimeError):
    """Raised when the platform is misconfigured, e.g. no default plan seeded."""


def _coerce(value: str, value_type: ValueType) -> FeatureValue:
    if value_type is ValueType.BOOL:
        return value.strip().lower() in ("1", "true", "yes", "on")
    if value_type is ValueType.INT:
        return int(value)
    return value


@dataclass(frozen=True)
class Entitlements:
    """An immutable snapshot of one user's limits, resolved for this request."""

    plan_code: str
    plan_name: str
    subscription_status: str | None
    values: dict[str, FeatureValue] = field(default_factory=dict)

    def get(self, key: str, default: FeatureValue | None = None) -> FeatureValue | None:
        return self.values.get(key, default)

    def allows(self, key: str) -> bool:
        """True for a boolean feature that is on, or a numeric limit above zero."""
        value = self.values.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value == UNLIMITED or value > 0
        return value is not None

    def limit(self, key: str) -> int:
        """Numeric ceiling for `key`. UNLIMITED (-1) means no ceiling."""
        value = self.values.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise EntitlementError(f"Feature {key!r} is not a numeric limit")
        return value

    def is_unlimited(self, key: str) -> bool:
        return self.limit(key) == UNLIMITED

    def within_limit(self, key: str, current_count: int) -> bool:
        """Whether one more of `key` is permitted given `current_count` already used."""
        ceiling = self.limit(key)
        return True if ceiling == UNLIMITED else current_count < ceiling


def _load_plan(db: Session, code: str) -> Plan:
    plan = db.scalars(
        select(Plan).options(selectinload(Plan.features)).where(Plan.code == code)
    ).first()
    if plan is None:
        raise EntitlementError(f"Plan {code!r} is not seeded. Run: python -m app.db.seed")
    return plan


def _entitlements_from_plan(plan: Plan, status: SubscriptionStatus | None) -> Entitlements:
    return Entitlements(
        plan_code=plan.code,
        plan_name=plan.name,
        subscription_status=status.value if status else None,
        values={f.feature_key: _coerce(f.value, f.value_type) for f in plan.features},
    )


def active_subscription(db: Session, user_id: uuid.UUID) -> Subscription | None:
    """The subscription that currently grants access, if any."""
    return db.scalars(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]),
        )
        .order_by(Subscription.created_at.desc())
    ).first()


def resolve_for_user(db: Session, user: User) -> Entitlements:
    """Resolve entitlements for an authenticated user.

    Falls back to the free plan when there is no access-granting subscription -
    a lapsed or canceled subscriber is a free user, not a locked-out one.
    """
    subscription = active_subscription(db, user.id)
    if subscription is not None:
        return _entitlements_from_plan(subscription.plan, subscription.status)
    return _entitlements_from_plan(_load_plan(db, F.DEFAULT_PLAN_CODE), None)


def resolve_anonymous(db: Session) -> Entitlements:
    """Entitlements for a logged-out visitor: the free plan."""
    return _entitlements_from_plan(_load_plan(db, F.DEFAULT_PLAN_CODE), None)
