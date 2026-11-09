"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from app.models.analyst import AiMessage
from app.models.calendar import EarningsEvent
from app.models.chat import ChatFlag, ChatMessage, ChatRoom
from app.models.feed import FeedCategory, FeedItem, FeedItemTicker
from app.models.market import LatestQuote, PriceBar, SignalSnapshot
from app.models.plan import Plan, PlanFeature, ValueType
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.ticker import Ticker
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "AiMessage",
    "ChatFlag",
    "ChatMessage",
    "ChatRoom",
    "EarningsEvent",
    "FeedCategory",
    "FeedItem",
    "FeedItemTicker",
    "LatestQuote",
    "PriceBar",
    "SignalSnapshot",
    "Plan",
    "PlanFeature",
    "Subscription",
    "SubscriptionStatus",
    "Ticker",
    "User",
    "ValueType",
    "Watchlist",
    "WatchlistItem",
]
