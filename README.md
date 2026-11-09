# Market Intelligence Platform

Subscription market-intelligence web app: a free Big 7 dashboard with directional
signals, a categorised news and social feed, paywalled extended markets, and an AI
analyst with community chatrooms.

**Stack:** Next.js 16 · FastAPI · Postgres (Neon) · Redis (Upstash) · Stripe · LLM (RAG)

**Status: Phases 1-5 built** (Phase 5 partially: extended markets and theming are
done; Stripe and the legal pages are not). Live Big 7 dashboard with
prices, sparklines and explainable signals, pushed over server-sent events. Without a
`FINNHUB_API_KEY` it runs on clearly labelled simulated data. The news feed below the
dashboard is live: deduplicated headlines, categorised, with per-ticker sentiment that
feeds the signal. The AI analyst answers questions from that feed with a citation on
every claim, and the community chatrooms are open with an automatic spam screen and
moderation tooling. Extended markets adds a sector heatmap across 48 companies - our own
treemap, not an embed - and an earnings calendar, both partially available on Free and in
full on Plus and Pro. The whole app ships in light, dark and auto themes.

**Running on real Finnhub prices.** Quotes and company profiles are live. Signals and
sparklines need daily price history, which Finnhub's free tier does not serve
(`/stock/candle` returns 403), so they stay blank until `TWELVEDATA_API_KEY` is set - the
dashboard shows "No signal yet" rather than a score computed from nothing.

Engineering conventions, architecture rules and phase status live in
[CLAUDE.md](CLAUDE.md). Read that before changing code.

---

## Quick start

Requires Docker Desktop running, Python 3.11+, Node 20+.

```bash
docker compose up -d                       # Postgres (pgvector) :5433, Redis :6380

python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e "./apps/api[dev]" -e "./apps/worker[dev]"
# Create .env at the repo root — CLAUDE.md §4 "Settings" lists every key.

cd apps/api
../../.venv/Scripts/python.exe -m alembic upgrade head
../../.venv/Scripts/python.exe -m app.db.seed
../../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

In a second shell, the worker (fills prices and signals):

```bash
cd apps/worker
../../.venv/Scripts/python.exe -m worker.main
```

In a third shell:

```bash
npm install            # from the repo root - apps/web is an npm workspace
npm run dev:web        # http://localhost:3000
```

For real prices, add `FINNHUB_API_KEY` (quotes) and `TWELVEDATA_API_KEY` (daily bars) to
`.env`. Both have free tiers.

On Linux/macOS use `.venv/bin/python` instead of `./.venv/Scripts/python.exe`.

- Web: http://localhost:3000
- API docs (OpenAPI): http://localhost:8000/docs
- Readiness: http://localhost:8000/health/ready

## Tests

```bash
cd apps/api    && ../../.venv/Scripts/python.exe -m pytest      # 286 tests
cd apps/worker && ../../.venv/Scripts/python.exe -m pytest      #  15 tests
npm run test:web                                                #  47 tests
```

The Python suites run against a real Postgres (`mip_test`, created and migrated
automatically) and a real Redis (logical db 15) — not SQLite or mocks — so native enums,
`ON DELETE` rules, the Lua rate limiter and pub/sub are actually exercised. Provider
HTTP calls are mocked; no test touches the network. Every run applies the Alembic migrations and checks them for drift
against the models.

## Layout

```
apps/api      FastAPI: auth, entitlements, plan catalogue. The shared domain layer.
apps/worker   APScheduler jobs; imports the API package for models and settings.
apps/web      Next.js App Router, TypeScript, Tailwind v4.
```

## The plan matrix

Every access decision reads `plans` + `plan_features` — there is no `if plan == "pro"`
anywhere in the codebase. Changing a price or a limit is a database row, not a deploy.

| Capability | Free | Plus | Pro |
|---|---|---|---|
| Big 7 dashboard | Yes | Yes | Yes |
| News/social feed (all categories) | Yes | Yes | Yes |
| Custom tickers | — | 15 | Unlimited |
| Sector heatmap + earnings calendar | Sector totals, 7-day calendar | Full | Full |
| AI analyst messages | 5 / day | 50 / day | Fair use |
| Chatrooms | Read-only | Read + post | Read + post |
| Data refresh interval | 5 min | 60 sec | 15 sec |

Prices are placeholders until the matrix is signed off with the client.

## Licence

Proprietary — client project.
