"""Canonical feature keys - the row labels of the section 1 plan matrix.

Code refers to these constants; the *values* live in `plan_features`. Adding a
tier or changing a limit is a DB row, never a deploy.
"""

from __future__ import annotations

from typing import Final

# Free surfaces
BIG7_DASHBOARD: Final = "dashboard.big7"
NEWS_FEED_ALL_CATEGORIES: Final = "feed.all_categories"

# Gated surfaces
CUSTOM_TICKER_LIMIT: Final = "dashboard.custom_ticker_limit"
EXTENDED_MARKETS_ACCESS: Final = "markets.extended_access"  # delayed | full

# AI analyst
AI_MESSAGES_PER_DAY: Final = "ai.messages_per_day"
AI_MESSAGES_PER_HOUR: Final = "ai.messages_per_hour"  # fair-use abuse guard

# Chat
CHAT_CAN_READ: Final = "chat.can_read"
CHAT_CAN_POST: Final = "chat.can_post"

# Data freshness
REFRESH_INTERVAL_SECONDS: Final = "data.refresh_interval_seconds"

ALL_FEATURE_KEYS: Final[tuple[str, ...]] = (
    BIG7_DASHBOARD,
    NEWS_FEED_ALL_CATEGORIES,
    CUSTOM_TICKER_LIMIT,
    EXTENDED_MARKETS_ACCESS,
    AI_MESSAGES_PER_DAY,
    AI_MESSAGES_PER_HOUR,
    CHAT_CAN_READ,
    CHAT_CAN_POST,
    REFRESH_INTERVAL_SECONDS,
)

DEFAULT_PLAN_CODE: Final = "free"
