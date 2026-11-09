"""Reference data: the plan matrix and the Big 7 universe.

This is the section 1 table of the build plan, expressed as rows. Changing a
limit here (or directly in the database) changes behaviour with no deploy.

Idempotent - safe to run on every deploy. Run with:

    python -m app.db.seed
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.chat import ChatRoom
from app.models.feed import FeedCategory
from app.models.plan import UNLIMITED, Plan, PlanFeature, ValueType
from app.models.ticker import Ticker
from app.services import features as F

log = get_logger("db.seed")


@dataclass(frozen=True)
class PlanSpec:
    code: str
    name: str
    description: str
    price_cents_monthly: int
    sort_order: int
    features: dict[str, tuple[ValueType, str, str]]  # key -> (type, value, description)


_BOOL, _INT, _STR = ValueType.BOOL, ValueType.INT, ValueType.STRING

PLAN_MATRIX: tuple[PlanSpec, ...] = (
    PlanSpec(
        code="free",
        name="Free",
        description="Big 7 dashboard and the full news and social feed.",
        price_cents_monthly=0,
        sort_order=0,
        features={
            F.BIG7_DASHBOARD: (_BOOL, "true", "Big 7 ticker dashboard"),
            F.NEWS_FEED_ALL_CATEGORIES: (_BOOL, "true", "All feed categories"),
            F.CUSTOM_TICKER_LIMIT: (_INT, "0", "No custom tickers"),
            F.EXTENDED_MARKETS_ACCESS: (_STR, "delayed", "Heatmap and calendar, delayed/partial"),
            F.AI_MESSAGES_PER_DAY: (_INT, "5", "5 AI analyst messages per day"),
            F.AI_MESSAGES_PER_HOUR: (_INT, "5", "Hourly abuse guard"),
            F.CHAT_CAN_READ: (_BOOL, "true", "Read chatrooms"),
            F.CHAT_CAN_POST: (_BOOL, "false", "Cannot post in chatrooms"),
            F.REFRESH_INTERVAL_SECONDS: (_INT, "300", "5 minute refresh"),
        },
    ),
    PlanSpec(
        code="plus",
        name="Plus",
        description="Custom tickers, full extended markets, and a metered AI analyst.",
        # Placeholder price. Locked with the client in Week 1 (section 8, item 2).
        price_cents_monthly=1900,
        sort_order=1,
        features={
            F.BIG7_DASHBOARD: (_BOOL, "true", "Big 7 ticker dashboard"),
            F.NEWS_FEED_ALL_CATEGORIES: (_BOOL, "true", "All feed categories"),
            F.CUSTOM_TICKER_LIMIT: (_INT, "15", "Up to 15 custom tickers"),
            F.EXTENDED_MARKETS_ACCESS: (_STR, "full", "Full heatmap and economic calendar"),
            F.AI_MESSAGES_PER_DAY: (_INT, "50", "50 AI analyst messages per day"),
            F.AI_MESSAGES_PER_HOUR: (_INT, "20", "Hourly abuse guard"),
            F.CHAT_CAN_READ: (_BOOL, "true", "Read chatrooms"),
            F.CHAT_CAN_POST: (_BOOL, "true", "Post in chatrooms"),
            F.REFRESH_INTERVAL_SECONDS: (_INT, "60", "60 second refresh"),
        },
    ),
    PlanSpec(
        code="pro",
        name="Pro",
        description="Unlimited tickers and fair-use AI, at the fastest refresh rate.",
        price_cents_monthly=4900,
        sort_order=2,
        features={
            F.BIG7_DASHBOARD: (_BOOL, "true", "Big 7 ticker dashboard"),
            F.NEWS_FEED_ALL_CATEGORIES: (_BOOL, "true", "All feed categories"),
            F.CUSTOM_TICKER_LIMIT: (_INT, str(UNLIMITED), "Unlimited custom tickers"),
            F.EXTENDED_MARKETS_ACCESS: (_STR, "full", "Full heatmap and economic calendar"),
            # Fair use, not metered: no daily cap, but an hourly abuse guard that
            # the fair-use policy states out loud (build plan, Phase 4).
            F.AI_MESSAGES_PER_DAY: (_INT, str(UNLIMITED), "Fair use - no daily cap"),
            F.AI_MESSAGES_PER_HOUR: (_INT, "40", "Fair-use guard: 40 messages/hour"),
            F.CHAT_CAN_READ: (_BOOL, "true", "Read chatrooms"),
            F.CHAT_CAN_POST: (_BOOL, "true", "Post in chatrooms"),
            F.REFRESH_INTERVAL_SECONDS: (_INT, "15", "15 second refresh"),
        },
    ),
)

BIG7: tuple[tuple[str, str, str, str], ...] = (
    ("AAPL", "Apple Inc.", "NASDAQ", "Technology"),
    ("MSFT", "Microsoft Corporation", "NASDAQ", "Technology"),
    ("GOOGL", "Alphabet Inc. Class A", "NASDAQ", "Communication Services"),
    ("AMZN", "Amazon.com Inc.", "NASDAQ", "Consumer Discretionary"),
    ("NVDA", "NVIDIA Corporation", "NASDAQ", "Technology"),
    ("META", "Meta Platforms Inc.", "NASDAQ", "Communication Services"),
    ("TSLA", "Tesla Inc.", "NASDAQ", "Consumer Discretionary"),
)


#: The wider universe behind the extended-markets heatmap (Phase 5). The Big 7
#: alone span three sectors, which is not a market map - a heatmap needs every
#: sector present or the gaps read as "nothing happened there".
#:
#: Large, liquid US names, four to five per GICS sector. The *sector* here is a
#: seeded default so a tile exists before the nightly profile job has run;
#: `refresh_profiles` overwrites `industry` and `market_cap` from the provider
#: but leaves these labels alone, because the provider's own sector taxonomy
#: does not match GICS and a heatmap with two naming schemes in it is unreadable.
#:
#: These refresh on `universe_quote_interval_seconds`, well behind the Big 7:
#: quoting all of them every 60 s would spend the whole free-tier minute budget.
UNIVERSE: tuple[tuple[str, str, str, str], ...] = (
    # Technology
    ("AVGO", "Broadcom Inc.", "NASDAQ", "Technology"),
    ("AMD", "Advanced Micro Devices Inc.", "NASDAQ", "Technology"),
    ("CRM", "Salesforce Inc.", "NYSE", "Technology"),
    ("ORCL", "Oracle Corporation", "NYSE", "Technology"),
    # Communication Services
    ("NFLX", "Netflix Inc.", "NASDAQ", "Communication Services"),
    ("DIS", "The Walt Disney Company", "NYSE", "Communication Services"),
    ("T", "AT&T Inc.", "NYSE", "Communication Services"),
    ("VZ", "Verizon Communications Inc.", "NYSE", "Communication Services"),
    # Consumer Discretionary
    ("HD", "The Home Depot Inc.", "NYSE", "Consumer Discretionary"),
    ("MCD", "McDonald's Corporation", "NYSE", "Consumer Discretionary"),
    ("NKE", "NIKE Inc.", "NYSE", "Consumer Discretionary"),
    ("SBUX", "Starbucks Corporation", "NASDAQ", "Consumer Discretionary"),
    # Consumer Staples
    ("WMT", "Walmart Inc.", "NYSE", "Consumer Staples"),
    ("PG", "The Procter & Gamble Company", "NYSE", "Consumer Staples"),
    ("KO", "The Coca-Cola Company", "NYSE", "Consumer Staples"),
    ("COST", "Costco Wholesale Corporation", "NASDAQ", "Consumer Staples"),
    # Financials
    ("JPM", "JPMorgan Chase & Co.", "NYSE", "Financials"),
    ("BAC", "Bank of America Corporation", "NYSE", "Financials"),
    ("V", "Visa Inc.", "NYSE", "Financials"),
    ("GS", "The Goldman Sachs Group Inc.", "NYSE", "Financials"),
    # Health Care
    ("JNJ", "Johnson & Johnson", "NYSE", "Health Care"),
    ("UNH", "UnitedHealth Group Incorporated", "NYSE", "Health Care"),
    ("LLY", "Eli Lilly and Company", "NYSE", "Health Care"),
    ("PFE", "Pfizer Inc.", "NYSE", "Health Care"),
    # Industrials
    ("CAT", "Caterpillar Inc.", "NYSE", "Industrials"),
    ("BA", "The Boeing Company", "NYSE", "Industrials"),
    ("HON", "Honeywell International Inc.", "NASDAQ", "Industrials"),
    ("UPS", "United Parcel Service Inc.", "NYSE", "Industrials"),
    # Energy
    ("XOM", "Exxon Mobil Corporation", "NYSE", "Energy"),
    ("CVX", "Chevron Corporation", "NYSE", "Energy"),
    ("COP", "ConocoPhillips", "NYSE", "Energy"),
    ("SLB", "Schlumberger N.V.", "NYSE", "Energy"),
    # Utilities
    ("NEE", "NextEra Energy Inc.", "NYSE", "Utilities"),
    ("DUK", "Duke Energy Corporation", "NYSE", "Utilities"),
    ("SO", "The Southern Company", "NYSE", "Utilities"),
    # Real Estate
    ("PLD", "Prologis Inc.", "NYSE", "Real Estate"),
    ("AMT", "American Tower Corporation", "NYSE", "Real Estate"),
    ("SPG", "Simon Property Group Inc.", "NYSE", "Real Estate"),
    # Materials
    ("LIN", "Linde plc", "NASDAQ", "Materials"),
    ("SHW", "The Sherwin-Williams Company", "NYSE", "Materials"),
    ("FCX", "Freeport-McMoRan Inc.", "NYSE", "Materials"),
)


#: (key, label, description). The build plan names these categories; the
#: descriptions are what the classifier is given, so they define the boundary.
FEED_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "earnings",
        "Earnings",
        "Quarterly results, guidance, revenue or margin figures, and analyst "
        "estimate revisions tied to reported numbers.",
    ),
    (
        "central-banks",
        "Central banks",
        "Interest rate decisions, inflation data, and central bank commentary "
        "from the Fed, ECB, BoE or others.",
    ),
    (
        "international-policy",
        "International policy",
        "Tariffs, sanctions, trade agreements, export controls, and "
        "geopolitical events affecting companies or markets.",
    ),
    (
        "regulation",
        "Regulation & legal",
        "Antitrust, lawsuits, regulatory investigations, fines, and compliance "
        "rulings involving a company.",
    ),
    (
        "tech",
        "Technology",
        "Product launches, AI and chip developments, software and cloud, "
        "research breakthroughs, and technical partnerships.",
    ),
    (
        "oil",
        "Oil & energy",
        "Crude and natural gas prices, OPEC decisions, energy supply and "
        "demand, and renewable energy policy.",
    ),
    (
        "bitcoin",
        "Crypto",
        "Bitcoin and other cryptocurrencies, digital asset regulation, "
        "exchanges, and corporate crypto holdings.",
    ),
    (
        "markets",
        "Markets",
        "Index moves, sector rotation, volatility, and commentary about price "
        "action that is not specific to one company's business.",
    ),
)


#: (slug, name, description). Rooms are rows so one can be closed - or a new
#: one opened for an event - without a deploy.
CHAT_ROOMS: tuple[tuple[str, str, str], ...] = (
    ("general", "General", "Markets, news and anything else."),
    ("big7", "Big 7", "Apple, Microsoft, Alphabet, Amazon, Nvidia, Meta and Tesla."),
    ("earnings", "Earnings", "Results, guidance and the reaction to them."),
    ("macro", "Macro", "Rates, inflation, oil and policy."),
)


def seed_plans(db: Session) -> None:
    for spec in PLAN_MATRIX:
        plan = db.scalars(select(Plan).where(Plan.code == spec.code)).first()
        if plan is None:
            plan = Plan(code=spec.code)
            db.add(plan)

        plan.name = spec.name
        plan.description = spec.description
        plan.price_cents_monthly = spec.price_cents_monthly
        plan.sort_order = spec.sort_order
        plan.is_active = True
        db.flush()

        existing = {f.feature_key: f for f in plan.features}
        for key, (value_type, value, description) in spec.features.items():
            feature = existing.get(key)
            if feature is None:
                feature = PlanFeature(plan_id=plan.id, feature_key=key)
                db.add(feature)
            feature.value_type = value_type
            feature.value = value
            feature.description = description

        # A key removed from the matrix must disappear, or stale limits linger.
        for key, feature in existing.items():
            if key not in spec.features:
                db.delete(feature)

    db.flush()


def _upsert_ticker(
    db: Session,
    symbol: str,
    name: str,
    exchange: str,
    sector: str,
    *,
    is_big7: bool,
    big7_order: int,
) -> None:
    ticker = db.scalars(select(Ticker).where(Ticker.symbol == symbol)).first()
    if ticker is None:
        ticker = Ticker(symbol=symbol)
        db.add(ticker)
    ticker.name = name
    ticker.exchange = exchange
    ticker.sector = sector
    ticker.currency = "USD"
    ticker.is_big7 = is_big7
    ticker.big7_order = big7_order
    ticker.is_active = True


def seed_tickers(db: Session) -> None:
    """The Big 7, plus the wider universe the extended-markets heatmap needs.

    `is_big7` is what separates them: the homepage and the signal engine read
    only the Big 7, while the heatmap reads every active name. That one flag is
    why adding forty tickers does not change the free dashboard or multiply the
    LLM spend.
    """
    for order, (symbol, name, exchange, sector) in enumerate(BIG7):
        _upsert_ticker(db, symbol, name, exchange, sector, is_big7=True, big7_order=order)
    for symbol, name, exchange, sector in UNIVERSE:
        _upsert_ticker(db, symbol, name, exchange, sector, is_big7=False, big7_order=0)
    db.flush()


def seed_categories(db: Session) -> None:
    """The feed taxonomy. Rows, not an enum, so it can change without a deploy.

    The `description` is not decoration: it is sent to the model as the
    definition of the category, so wording it carefully is how classification
    accuracy is tuned - by editing a row, not by changing code.
    """
    for order, (key, label, description) in enumerate(FEED_CATEGORIES):
        category = db.scalars(select(FeedCategory).where(FeedCategory.key == key)).first()
        if category is None:
            category = FeedCategory(key=key)
            db.add(category)
        category.label = label
        category.description = description
        category.sort_order = order
        category.is_active = True
    db.flush()


def seed_rooms(db: Session) -> None:
    """The chatroom list. Data, like the plan matrix and the feed taxonomy."""
    for order, (slug, name, description) in enumerate(CHAT_ROOMS):
        room = db.scalars(select(ChatRoom).where(ChatRoom.slug == slug)).first()
        if room is None:
            room = ChatRoom(slug=slug)
            db.add(room)
        room.name = name
        room.description = description
        room.sort_order = order
        room.is_active = True
    db.flush()


def seed_all(db: Session) -> None:
    seed_plans(db)
    seed_tickers(db)
    seed_categories(db)
    seed_rooms(db)
    db.commit()


def main() -> None:
    configure_logging(settings)
    with SessionLocal() as db:
        seed_all(db)
    log.info(
        "seed_complete",
        plans=len(PLAN_MATRIX),
        big7=len(BIG7),
        universe=len(UNIVERSE),
        categories=len(FEED_CATEGORIES),
        rooms=len(CHAT_ROOMS),
    )


if __name__ == "__main__":
    main()
