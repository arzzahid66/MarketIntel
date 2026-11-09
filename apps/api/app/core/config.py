"""Application settings.

Everything configurable comes from the environment. There are no hardcoded
secrets and no per-environment `if` branches scattered through the code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_title: str = "Market Intelligence Platform API"
    api_version: str = "0.1.0"

    # --- Database ---
    database_url: str = "postgresql+psycopg://mip:mip@localhost:5433/mip"

    # --- Redis ---
    redis_url: str = "redis://localhost:6380/0"

    # --- Auth ---
    auth_provider: Literal["local", "clerk"] = "local"
    jwt_secret: str = "dev-only-change-me-in-every-real-environment"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 30
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""

    # --- Market data (Phase 2) ---
    # auto    -> Finnhub when FINNHUB_API_KEY is set, otherwise the simulated provider.
    # fake    -> always simulated. The UI labels it "Simulated data" everywhere.
    # finnhub -> always Finnhub; boot fails if the key is missing.
    market_data_provider: Literal["auto", "fake", "finnhub"] = "auto"
    finnhub_api_key: SecretStr = SecretStr("")
    # Finnhub's free tier no longer serves daily candles. When this key is set,
    # daily OHLCV comes from Twelve Data instead; quotes still come from Finnhub.
    twelvedata_api_key: SecretStr = SecretStr("")
    # Kept under each provider's published free-tier limits (60/min and 8/min).
    finnhub_calls_per_minute: int = 55
    twelvedata_calls_per_minute: int = 7
    provider_timeout_seconds: float = 8.0

    quote_ingest_interval_seconds: int = 60
    signal_interval_seconds: int = 300
    bars_backfill_sessions: int = 150

    # --- LLM (Phase 3: news scoring) ---
    # auto   -> OpenAI when OPENAI_API_KEY is set, otherwise simulated.
    # fake   -> always the deterministic keyword scorer. Never in production.
    # openai -> always OpenAI; boot fails if the key is missing.
    llm_provider: Literal["auto", "fake", "openai"] = "auto"
    openai_api_key: SecretStr = SecretStr("")
    # Scoring runs once per article at ingest, so cost per call dominates. This
    # model also accepts temperature=0, which newer ones refuse - see openai.py.
    llm_model: str = "gpt-4.1-mini"
    llm_calls_per_minute: int = 50
    llm_timeout_seconds: float = 30.0

    # --- News feed (Phase 3) ---
    # auto -> Finnhub company news when FINNHUB_API_KEY is set, else simulated.
    news_source: Literal["auto", "fake", "finnhub"] = "auto"
    news_ingest_interval_seconds: int = 900
    news_score_interval_seconds: int = 120
    #: How far back the first ingest reaches. Later runs only fetch the gap.
    news_backfill_days: int = 7
    #: Articles scored per cycle. Caps spend per run and keeps one slow batch
    #: from blocking the scheduler; the backlog drains over several cycles.
    news_score_batch: int = 20
    #: Give up on an article after this many scoring failures, so one unparseable
    #: item cannot be retried forever.
    news_max_score_attempts: int = 3
    #: Articles embedded per cycle. One request per batch, so this is also
    #: the batch size sent to the embeddings API.
    news_embed_batch: int = 64
    news_embed_interval_seconds: int = 180

    # --- Extended markets (Phase 5) ---
    # auto -> Finnhub earnings calendar when FINNHUB_API_KEY is set, else simulated.
    # Earnings, not macro: Finnhub's free tier returns 403 on /calendar/economic
    # and 200 on /calendar/earnings. See sources/calendar_base.py.
    calendar_source: Literal["auto", "fake", "finnhub"] = "auto"
    calendar_ingest_interval_seconds: int = 6 * 3600
    #: How far back and forward the calendar reaches. Backward so a result that
    #: has just landed still shows its actual next to the estimate.
    calendar_lookback_days: int = 7
    calendar_horizon_days: int = 30
    #: The wider universe refreshes on its own interval, well behind the Big 7.
    #: The whole universe on the Big 7's 60s cadence would spend the entire
    #: free-tier minute budget on a page nobody is watching tick by tick.
    universe_quote_interval_seconds: int = 300

    # --- CORS ---
    cors_origins: str = "http://localhost:3000"

    # --- Observability ---
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    @field_validator("database_url")
    @classmethod
    def _normalise_driver(cls, v: str) -> str:
        """Accept the bare `postgresql://` URL Neon hands out and point it at psycopg3."""
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def assert_production_safe(self) -> None:
        """Fail fast at boot rather than silently running production on dev defaults."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.jwt_secret == "dev-only-change-me-in-every-real-environment":
            problems.append("JWT_SECRET is still the development default")
        if self.auth_provider == "local":
            problems.append("AUTH_PROVIDER=local is not permitted in production")
        if "localhost" in self.database_url:
            problems.append("DATABASE_URL points at localhost")
        if self.market_data_provider == "fake":
            problems.append("MARKET_DATA_PROVIDER=fake would show simulated prices to customers")
        if not self.finnhub_api_key.get_secret_value():
            problems.append("FINNHUB_API_KEY is not set")
        if self.llm_provider == "fake":
            problems.append("LLM_PROVIDER=fake would score news with a keyword stub")
        if self.news_source == "fake":
            problems.append("NEWS_SOURCE=fake would show invented headlines to customers")
        if self.calendar_source == "fake":
            problems.append("CALENDAR_SOURCE=fake would show invented earnings dates")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
