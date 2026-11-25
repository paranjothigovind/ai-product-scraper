# AI Product Scraper

Scrapes product listings from a URL (or pasted HTML), validates and scores the results, ranks the products, and stores each run in Postgres. The crawl is a LangGraph state machine with checkpointing, so a crashed run resumes from its last checkpoint.

> **Status: work in progress.** The Python backend is built through phase 4: HTML extraction, the crawl graph, persistence, evaluation and ranking. The LLM extractor, the HTTP API, the job queue and the client UI are not built yet (see [Roadmap](#roadmap)).

## Repository layout

| Path | What it is |
| --- | --- |
| `backend/` | Python 3.12 backend (the active codebase) |
| `client/` | Next.js 15 / React 19 / Tailwind 4 client. Scaffold only: the scrape form is planned for phase 9 |
| `legacy-ts/` | Earlier TypeScript monorepo (pnpm, Drizzle). Superseded by `backend/` and kept for reference |
| `docker-compose.yml` | Local infrastructure: Postgres 16 (host port 5433), Redis 7, an S3-compatible store (adobe/s3mock) |
| `docs/runbooks/` | Placeholder for runbooks |

## Backend

Source is in `backend/src/scraper/`:

| Package | Responsibility |
| --- | --- |
| `schemas/` | Pydantic models: scrape request, product, result, error codes, eval |
| `html/` | Hostile-input-safe HTML parsing: decoding, DOM, CSS selectors, JSON-LD, microdata, schema.org, text and value normalisation |
| `tools/` | `scrape_html` (fetch and extract), `paginate`, `validate_products`, URL helpers |
| `security/` | SSRF protection, `robots.txt` handling, per-domain rate limiting |
| `graph/` | LangGraph crawl: `init → guard → pick → ingest → prepare → extract → paginate → validate`, looping until a limit is hit, then `truncate → evaluate → rank → persist → finalize`. Includes the Postgres checkpointer and `run_graph`, which starts or resumes a run |
| `eval/` | Quality metrics (schema validity, field coverage, plausibility, volume, groundedness) with configurable weights |
| `ranking/` | Weighted product ranking by rating, review count and completeness |
| `db/` | SQLAlchemy async models, repository, session, Alembic migrations |
| `core/` | Settings (validated at startup) and error types |
| `llm/` | Product extractor behind one interface, with Anthropic and Azure OpenAI backends (structured output), used only for pages with no JSON-LD/microdata products |
| `agents/`, `api/`, `queue/` | Empty packages reserved for later phases |

### Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker (for local Postgres, and for the integration tests via testcontainers)

### Setup

```bash
# 1. Start infrastructure (Postgres, Redis, S3-compatible store with the scraper-html bucket)
docker compose up -d

# 2. Configure the environment
cp .env.example .env        # then set ANTHROPIC_API_KEY

# 3. Install and migrate
cd backend
uv sync
uv run alembic upgrade head
```

Settings are loaded from `.env` and validated at startup, so a bad environment fails before any work starts.

### Configuration

| Variable | Purpose | Default in `.env.example` |
| --- | --- | --- |
| `LLM_PROVIDER` | `anthropic` or `azure` | `azure` |
| `ANTHROPIC_API_KEY` | Anthropic key (required when provider is `anthropic`) | empty |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION` | Azure OpenAI / Foundry resource (required when provider is `azure`) | empty |
| `MODEL_EXTRACT`, `MODEL_JUDGE` | Model ids, or Azure deployment names | `gpt-4o-mini` |
| `MODEL_ESCALATE` | Model used when escalating a retry (not wired yet) | `gpt-4o-mini` |
| `DATABASE_URL` | Postgres DSN (`postgresql+asyncpg://`) | local compose Postgres (port 5433) |
| `REDIS_URL` | Redis URL | `redis://localhost:6379` |
| `S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Object storage for raw HTML | local S3 mock |
| `MAX_PAGES_TOTAL` | Page cap per run | `50` |
| `MAX_RETRIES` | Extraction retries | `2` |
| `MAX_TOKENS_PER_RUN` | Token budget per run | `200000` |
| `MIN_QUALITY` | Minimum quality score to accept a result | `0.75` |
| `PLAN_CAP_PRODUCTS` | Upper bound on `max_products` per request | `500` |

Also supported in `Settings`: `USER_AGENT` (set a real contact URL before crawling public sites) and `EGRESS_PROXY_URL`.

### Scrape request

A request supplies either a `url` or raw `html` (max 1 MB), plus:

- `max_products` (required, checked against the plan cap)
- `scope`: `site` (default) or `category`
- `max_pages`: optional per-request page limit
- `max_depth`: link depth, 0 to 5 (default 2)

Unknown fields are rejected.

### Development

```bash
cd backend
uv run pytest                    # unit tests
uv run pytest -m integration     # needs Postgres (TEST_DATABASE_URL, or Docker via testcontainers)
uv run ruff check .
uv run mypy                      # strict
```

Add a new migration with `uv run alembic revision -m "..."`.

## Client

```bash
cd client
cp .env.example .env.local       # NEXT_PUBLIC_API_URL, default http://localhost:8000
pnpm install
pnpm dev                         # also: build, lint, typecheck
```

The client currently renders a placeholder page.

## Roadmap

Open items are tracked as `TODO(next)` comments in the code. The main ones:

- **Phase 5 (remaining):** retry with feedback and model escalation from `evaluate` (the LLM extraction path itself is done), cost tracking in USD
- **Phase 7:** Redis-backed cross-process rate limiting, conditional GET and caching, circuit breaker, Playwright rendering tier
- **Phase 8:** Link discovery and navigation across listing pages
- **Phase 9:** Client scrape form
- API, worker and client services in `docker-compose.yml` once their Dockerfiles exist
- Separate API/worker database roles; the egress proxy must enforce the same IP blocklist as the SSRF guard
