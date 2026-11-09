from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.subscription import Subscription

#: Stored in `plan_features.value` for an integer feature that has no ceiling.
UNLIMITED = -1


class ValueType(enum.StrEnum):
    BOOL = "bool"
    INT = "int"
    STRING = "string"


class Plan(Base, TimestampMixin):
    """A sellable tier. Prices and limits are data, so changing them is a DB row."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents_monthly: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    # Populated in Phase 4. Nullable here so Phase 1 does not depend on Stripe.
    stripe_price_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    features: Mapped[list[PlanFeature]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="plan")

    def __repr__(self) -> str:
        return f"<Plan {self.code}>"


class PlanFeature(Base, TimestampMixin):
    """One capability limit for one plan - a single cell of the §1 plan matrix."""

    __tablename__ = "plan_features"
    __table_args__ = (UniqueConstraint("plan_id", "feature_key", name="uq_plan_feature"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    feature_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    value_type: Mapped[ValueType] = mapped_column(
        Enum(
            ValueType,
            name="plan_feature_value_type",
            native_enum=True,
            # Persist the lowercase values, not the member names, so the rows stay
            # readable to whoever edits the plan matrix in the database.
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    #: Always text on the wire; `ValueType` says how to read it.
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="features")

    def __repr__(self) -> str:
        return f"<PlanFeature {self.feature_key}={self.value}>"
