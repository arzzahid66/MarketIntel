/**
 * Mirrors the FastAPI response schemas (apps/api/app/schemas).
 *
 * Feature keys are duplicated here deliberately: the API exposes the canonical
 * list at GET /entitlements/keys, and `src/lib/features.test.ts` asserts this
 * file has not drifted from it.
 */

export type PlanCode = "free" | "plus" | "pro";

export const FEATURE = {
  BIG7_DASHBOARD: "dashboard.big7",
  NEWS_FEED_ALL_CATEGORIES: "feed.all_categories",
  CUSTOM_TICKER_LIMIT: "dashboard.custom_ticker_limit",
  EXTENDED_MARKETS_ACCESS: "markets.extended_access",
  AI_MESSAGES_PER_DAY: "ai.messages_per_day",
  AI_MESSAGES_PER_HOUR: "ai.messages_per_hour",
  CHAT_CAN_READ: "chat.can_read",
  CHAT_CAN_POST: "chat.can_post",
  REFRESH_INTERVAL_SECONDS: "data.refresh_interval_seconds",
} as const;

export type FeatureKey = (typeof FEATURE)[keyof typeof FEATURE];

/** A numeric limit of -1 means no ceiling. Matches UNLIMITED in the API. */
export const UNLIMITED = -1;

export type FeatureValue = boolean | number | string;

export interface Entitlements {
  plan_code: string;
  plan_name: string;
  subscription_status: string | null;
  features: Record<string, FeatureValue>;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  created_at: string;
}

export interface Session {
  user: User;
  entitlements: Entitlements;
}

export interface Ticker {
  symbol: string;
  name: string;
  exchange: string | null;
  sector: string | null;
  currency: string;
  is_big7: boolean;
}

export interface PlanFeature {
  feature_key: string;
  value_type: "bool" | "int" | "string";
  value: FeatureValue;
  description: string | null;
}

export interface Plan {
  code: string;
  name: string;
  description: string | null;
  price_cents_monthly: number;
  currency: string;
  sort_order: number;
  features: PlanFeature[];
}

export interface HealthResponse {
  status: string;
  environment: string;
  version: string;
  server_time: string;
}

/** The uniform error envelope every API error uses (app/core/errors.py). */
export interface ApiErrorBody {
  error: string;
  detail: unknown;
  status: number;
  request_id?: string;
}

/* ------------------------------------------------------------------------ */
/* Market dashboard (Phase 2) - mirrors apps/api/app/schemas/market.py        */
/* ------------------------------------------------------------------------ */

export type SignalBandCode =
  | "strong_bearish"
  | "bearish"
  | "neutral"
  | "bullish"
  | "strong_bullish";

export interface SignalComponent {
  key: string;
  label: string;
  weight: number;
  raw: number | null;
  normalized: number;
  contribution: number;
  available: boolean;
}

export interface Signal {
  score: number;
  band: SignalBandCode;
  computed_at: string;
  formula_version: number;
  components: SignalComponent[];
  notes: string[];
  intraday: boolean;
  as_of_session: string | null;
  is_stale: boolean;
  source: string;
}

/** live: intraday quote. close: a completed session's close. none: nothing yet. */
export type PriceBasis = "live" | "close" | "none";

export interface MarketRow {
  symbol: string;
  name: string;
  currency: string;
  price: number | null;
  change: number | null;
  change_percent: number | null;
  previous_close: number | null;
  price_basis: PriceBasis;
  as_of_session: string | null;
  provider_time: string | null;
  fetched_at: string | null;
  is_stale: boolean;
  sparkline: number[];
  signal: Signal | null;
  source: string | null;
}

export interface MarketStatus {
  is_open: boolean;
  session: "pre" | "regular" | "post" | "closed";
  reason: string | null;
  last_completed_session: string;
  next_open: string;
  next_close: string | null;
}

export type DataStatus = "live" | "closed" | "stale" | "unavailable";

export interface Dashboard {
  server_time: string;
  last_updated_at: string | null;
  market: MarketStatus;
  data_status: DataStatus;
  is_simulated: boolean;
  provider: string;
  refresh_interval_seconds: number;
  revalidating: boolean;
  rows: MarketRow[];
}

// --- News & social feed (Phase 3) ---

export interface FeedCategory {
  key: string;
  label: string;
}

export interface FeedTicker {
  symbol: string;
  sentiment: number | null;
  label: string | null;
  materiality: string | null;
  rationale: string | null;
}

export interface FeedItem {
  id: string;
  title: string;
  summary: string | null;
  /** Whether `summary` was written by the model rather than the publisher. */
  summary_is_ai: boolean;
  source_url: string;
  publisher: string;
  published_at: string;
  fetched_at: string;
  category: FeedCategory | null;
  tickers: FeedTicker[];
}

export interface Feed {
  server_time: string;
  categories: FeedCategory[];
  items: FeedItem[];
}

// --- AI analyst (Phase 4) ---

export interface AnalystCitation {
  number: number;
  feed_item_id: string;
  title: string;
  publisher: string;
  source_url: string;
  published_at: string;
}

export interface AnalystUsage {
  used_today: number;
  /** -1 means no daily ceiling (Pro fair use); the hourly guard still applies. */
  daily_limit: number;
  used_this_hour: number;
  hourly_limit: number;
}

export interface AnalystAnswer {
  answer: string;
  citations: AnalystCitation[];
  /** Articles retrieved before the model saw them. 0 means nothing relevant. */
  retrieved: number;
  model: string;
  server_time: string;
  usage: AnalystUsage;
}

export interface AnalystStatus {
  server_time: string;
  usage: AnalystUsage;
  searchable_articles: number;
}

// --- Chatrooms (Phase 4) ---

export interface ChatRoom {
  slug: string;
  name: string;
  description: string;
}

export interface ChatMessage {
  id: string;
  body: string;
  author: string;
  author_id: string;
  created_at: string;
  is_hidden: boolean;
  hidden_reason: string | null;
  flags: number;
  /** Moderator-only; null for ordinary readers. */
  spam_score: number | null;
  spam_label: string | null;
}

export interface ChatHistory {
  server_time: string;
  room: ChatRoom;
  messages: ChatMessage[];
  /** Whether this viewer's plan allows posting. Read access is free. */
  can_post: boolean;
}

// --- Extended markets (Phase 5) ---

/** The two values of the `markets.extended_access` plan feature. */
export type MarketAccess = "full" | "delayed";

export interface Constituent {
  symbol: string;
  name: string;
  market_cap: number | null;
  change_percent: number | null;
  price: number | null;
  is_big7: boolean;
}

export interface SectorTile {
  sector: string;
  /** Market-cap weighted. `null` means not computable - never render it as 0%. */
  change_percent: number | null;
  market_cap: number;
  /** 0..1 colour saturation; the sign of `change_percent` gives direction. */
  intensity: number;
  count: number;
  weighted_count: number;
  /** Empty on a `delayed` plan - the API omits them, the UI does not hide them. */
  constituents: Constituent[];
}

export interface Heatmap {
  server_time: string;
  access: MarketAccess;
  tiles: SectorTile[];
  is_simulated: boolean;
  covered: number;
  total: number;
}

export interface EarningsEvent {
  symbol: string;
  name: string | null;
  session_date: string;
  /** "bmo" (before open), "amc" (after close), or "" when unstated. */
  timing: string;
  fiscal_quarter: number | null;
  fiscal_year: number | null;
  eps_estimate: number | null;
  eps_actual: number | null;
  revenue_estimate: number | null;
  revenue_actual: number | null;
  source: string;
}

export interface EarningsCalendar {
  server_time: string;
  access: MarketAccess;
  since: string;
  until: string;
  /** The window a `full` plan would return, so the upgrade prompt can be specific. */
  full_until: string;
  events: EarningsEvent[];
}
