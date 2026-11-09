# Deploying the Market Intelligence Platform

For whoever puts this on real infrastructure. Read `CLAUDE.md` for how the code
works; this covers only where it runs and what it needs to boot.

---

## 1. This is three processes, not one

The single most common mistake here is assuming a Netlify or Vercel deploy is
the whole job. It is a third of it.

| Piece | What it is | Can Netlify/Vercel host it? |
|---|---|---|
| `apps/web` | Next.js 16 | **Yes** |
| `apps/api` | FastAPI (ASGI, serves SSE) | **No** - needs a resident server |
| `apps/worker` | APScheduler loop | **No** - needs an always-on process |
| Postgres | **with the `vector` extension** | No - use Neon |
| Redis | cache, token bucket, pub/sub | No - use Upstash |

**Without the worker the app renders empty.** It is what fetches quotes, news,
earnings and embeddings and computes signals. A host that sleeps the worker is
a host that breaks the product.

**Netlify does not support Docker.** Neither does Vercel. This is not a problem:
`docker-compose.yml` exists only to give you Postgres and Redis locally. In
production those are managed services and nothing is containerised, so no
Dockerfile is required anywhere.

### Recommended split

- `apps/web` -> **Netlify** (`netlify.toml` is committed)
- `apps/api` + `apps/worker` -> **Render** (`render.yaml` is committed)
- Postgres -> **Neon**, on a project with pgvector enabled
- Redis -> **Upstash**

---

## 2. About "free"

Checked November 2026: there is **no free tier that will run this properly.**

- Render free web services **sleep after 15 minutes idle**, and the free plan
  has no background workers at all.
- Fly.io's free allowance is now a short trial, not an ongoing tier.
- Koyeb's free compute has been withdrawn or scales to zero.

The web app and both data stores genuinely are free (Netlify + Neon + Upstash
free tiers are sufficient for staging). The API and worker are roughly
**$7/month each** on Render's Starter plan. Budget ~$14/month for a staging
environment that behaves like production.

### 2.1 The genuinely-free stack

It can be done for $0, and the codebase already supports it - but it is a
different shape, not the same deploy on cheaper plans.

**The unlock is `python -m worker.main --once`.** It already exists (it was
written as a CI smoke test), it runs all ten jobs in dependency order, and it
exits 0 / 1 on success / failure. Combined with the design rule that **every job
decides for itself whether there is work** (`quotes_needed`, `signals_needed`,
bars already current), a duplicate or missed run is harmless. That means the
always-on APScheduler loop can be replaced by an external scheduler calling
`--once`, with no code change.

| Piece | Free host | Catch |
|---|---|---|
| `apps/web` | Netlify / Vercel Hobby | SSE capped; polling becomes the transport |
| Postgres + pgvector | Neon free | 0.5 GB, autosuspends; first query after idle is slow |
| Redis | Upstash free | **10,000 commands/day** - see below |
| `apps/api` | Render free, or Cloud Run | Sleeps after 15 min; first request pays a cold start |
| `apps/worker` | **GitHub Actions cron** calling `--once` | 5-minute minimum interval, and runs are delayed under load |

Two honest caveats:

- **Upstash's 10k commands/day is the binding limit**, not compute. Quote ingest
  writes one key per ticker per cycle across 48 tickers; at the default
  intervals that exceeds 10k on a normal trading day. Raise
  `QUOTE_INGEST_INTERVAL_SECONDS` and `UNIVERSE_QUOTE_INTERVAL_SECONDS` if you
  stay on the free Redis. The circuit breaker means exhausting it degrades to
  Postgres rather than erroring, so the failure mode is "staler", not "broken".
- **A scheduled GitHub Actions workflow needs your database and API keys as
  repository secrets.** That is a real expansion of where your credentials live.
  Use a dedicated least-privilege Neon role, not the owner connection string.

**The better free option, if you will run a VM:** Oracle Cloud's Always Free
tier includes a persistent ARM instance large enough to run the API, the worker,
Postgres and Redis together under systemd - genuinely always-on, no sleeping, no
cron workaround, and SSE works. The cost is that you are now administering a
server, including its security updates.

If none of that appeals, the fallback is: accept a sleeping API, drop the
worker, and drive ingest from an external cron hitting a protected endpoint.
That changes the architecture and loses SSE. Do not do it without deciding
deliberately.

---

## 3. Launch blockers

These are not deployment steps. They are reasons not to make the site public.

| Blocker | Why it blocks |
|---|---|
| **No Terms of Service or Privacy Policy** | Build plan section 6 calls these launch blockers. The placeholder pages say they are undrafted on purpose - **do not replace them with invented text.** Needs the client's lawyer. |
| **No cookie consent** | Same. The app sets auth cookies and a theme cookie. |
| **No named human moderator** | The chatroom is public and has only an automated screen. The risk register calls a named moderator non-negotiable before launch. |
| **`AUTH_PROVIDER=local` is refused in production** | `assert_production_safe()` rejects it. Production **requires a configured Clerk account** - this is a hard boot failure, not a warning. |
| **No Stripe** | The paywall is enforced but takes no money. The `$19`/`$49` prices in `PLAN_MATRIX` are invented placeholders awaiting client sign-off. |
| **No `TWELVEDATA_API_KEY`** | Finnhub's free tier returns 403 on `/stock/candle`, so there is no daily history and **no signals** - the product's headline feature renders "No signal yet". |

Staging behind `noindex` and access control is fine today. A public launch is
not, until the first three rows are resolved.

---

## 3.1 Live data vs seeded data

Two different things get called "seeded", and only one of them is fake.

**`python -m app.db.seed` writes no market data at all.** Verified: it inserts
the plan matrix, the 48 `tickers` rows, 8 feed categories and 4 chat rooms -
catalogue and configuration, nothing more. There is not one price, headline or
earnings date in it. The ticker rows are just the list of companies to follow;
every number attached to them arrives from a provider. The seed is required, and
running it does not put fake data in your database.

**Simulated market data comes from the `fake` providers**, and that is what you
must keep out. Once the keys below are set and pinned, every figure is live:

| Surface | Live after deploy? | Source |
|---|---|---|
| Prices, change %, market cap | **Yes** | Finnhub `/quote`, `/stock/profile2` |
| News feed, sentiment, categories | **Yes** | Finnhub `/company-news` + OpenAI |
| Earnings calendar | **Yes** | Finnhub `/calendar/earnings` |
| AI analyst answers and citations | **Yes** | OpenAI over the real feed |
| Sector heatmap | **Yes** | computed from the live quotes |
| **Signals and sparklines** | **No** | need `TWELVEDATA_API_KEY`; Finnhub 403s on `/stock/candle` |

### Pin the providers, do not leave them on `auto`

All four of `MARKET_DATA_PROVIDER`, `LLM_PROVIDER`, `NEWS_SOURCE` and
`CALENDAR_SOURCE` default to `auto`, which means *"use the real provider if its
key is present, otherwise simulate"*. That is correct locally and **wrong for a
deployed environment**: measured with no key, `auto` returns a provider named
`simulated` for all four and raises nothing. One typo in a Render secret and the
site serves invented prices.

`render.yaml` and the ingest workflow therefore pin all four to the real
provider. A missing key is then a `RuntimeError` at boot - a deploy that fails
visibly rather than a site that lies quietly.

This matters most on **staging**, because `assert_production_safe()` only runs
when `ENVIRONMENT=production`. A staging deploy has no safety net except these
pins.

### If simulated rows ever reach the database

They are sticky. `price_bars` ingest is `ON CONFLICT DO NOTHING`, so real bars
will **not** overwrite simulated ones for the same session - the fake rows win
permanently, and the signal then scores a real price against fake history and
prints a confident, meaningless number. Clear them before ingesting real data
(the three `delete from ...` statements are in `CLAUDE.md` section 4), and check
with:

```sql
select source, count(*) from latest_quotes group by source;
select source, count(*) from price_bars    group by source;
```

Anything other than `finnhub` / `twelvedata` on a live deployment is a bug.

---

## 4. Order of operations

Do these in order; each step depends on the one before.

### 4.1 Before the first commit

```bash
git check-ignore -v .env server_cred/marketintel.pem   # both must print a match
git status --short                                     # no .pem, .env or .png
```

`server_cred/` holds a **private SSH key**. It is now in `.gitignore`, but check
anyway: a key committed once survives in history no matter what you delete
later. If it has already been committed, rotate the key - do not just remove it.

### 4.2 Provision the data stores

1. **Neon** - create the project, then enable pgvector. The schema needs it and
   migration `0004_ai_analyst` runs `CREATE EXTENSION IF NOT EXISTS vector`, so
   the role must be allowed to create extensions.
2. **Upstash** - create the Redis database. Note that `REDIS_URL` must be the
   `rediss://` (TLS) form.

Do not run migrations by hand. `render.yaml` runs `alembic upgrade head` and the
seed in the API's start command, so a fresh deploy builds its own schema and
reference data. The seed is idempotent.

### 4.3 Clerk - not needed on the free path

`render.yaml` sets `ENVIRONMENT=staging`, which skips
`assert_production_safe()`, so the deploy runs on the built-in bcrypt + JWT
auth and **no Clerk account is required today**.

That is a deliberate trade, not an oversight. Staging skips *every* check in
that function, including the ones that refuse to serve simulated data - which
is why the provider pins in section 3.1 are not optional on this path.

For a real production launch: create the Clerk application, take
`CLERK_JWKS_URL` and `CLERK_ISSUER` from its API keys page, set
`AUTH_PROVIDER=clerk` and `ENVIRONMENT=production`. The `users` row is
provisioned just-in-time on first request, so there is no user migration.

### 4.4 Render

New -> Blueprint -> point at the repo. It reads `render.yaml` and prompts for
every `sync: false` secret. `JWT_SECRET` is generated for you.

**The blueprint contains one service, on the free plan.** The worker is not in
it, because Render's free tier has no background workers at all - on the free
path, `.github/workflows/ingest.yml` does that job on a cron instead. The
resident worker is commented at the bottom of `render.yaml` for when there is a
budget; enable it **and delete the workflow**, or both will ingest and burn
double the provider quota.

Set `CORS_ORIGINS` to the exact web origin once the frontend has a URL - it is
a chicken-and-egg step, so expect to come back and edit it.

### 4.5 Netlify

Import the repo. `netlify.toml` sets the build; the one thing it cannot set is
`NEXT_PUBLIC_API_URL`, which must point at the Render API and is configured in
the Netlify UI. A wrong value here is a staging site silently reading
production data.

### 4.6 Verify, in this order

```bash
curl -s https://<api>/health/ready                 # 200
curl -s https://<api>/market/dashboard | head -c 400   # is_simulated must be false
curl -si https://<web>/ | grep -i x-robots-tag     # noindex on staging
```

Then in a browser: the dashboard shows real prices; `/markets` shows 11 sector
tiles; a Free account sees sector totals with **no constituent rows in the
network response**; a Plus account sees the breakdown.

Watch the Render worker log for `quotes_ingested`, `earnings_ingested` and
`news_ingested`. If `bars_ingest_failed` appears for every symbol, that is the
missing Twelve Data key, and it is expected until one exists.

---

## 5. Things that will surprise you

- **SSE is capped on Netlify.** A function is killed at ~10s, so
  `/api/market/stream` is cut. The dashboard falls back to polling, which means
  on Netlify polling *is* the transport. If live push matters, serve the web app
  from somewhere that supports long-lived connections.
- **`/demo/gated/*` is not routed in production.** It exists for the entitlement
  tests - nine of them, including the rule-2 downgrade guard - and
  `app/api/router.py` registers it only when `ENVIRONMENT != production`.
- **The first deploy's first page load is slow.** Redis is cold and the worker
  has not run yet, so the dashboard falls through to Postgres and finds nothing
  until the worker's start-up pass completes (a minute or two).
- **Never point a real quote key at simulated history.** If the database ever
  held simulated rows, clear them before going live, or the signal mixes real
  prices with fake history and prints a confident, meaningless score. The three
  `delete from ...` statements are in `CLAUDE.md` section 4.
- **The 72-hour soak has never been run.** Nothing in this stack has run
  unattended for longer than a working session. Staging is where that finally
  happens; watch `feed_stats()` for a growing `unscored` count, which means
  scoring cannot keep up with ingest.
