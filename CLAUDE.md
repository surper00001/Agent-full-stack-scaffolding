# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Enterprise AI Agent platform — FastAPI backend + React frontend. Two separate workspaces under the monorepo: `backend/` (Python, managed by uv) and `frontend/` (TypeScript, managed by npm).

## Backend commands

All run from `backend/`:

```bash
# Start dev server (auto-creates tables in non-production)
uv run uvicorn src.main:app --reload --port 8000

# Lint & type-check
uv run ruff check src/
uv run mypy src/

# Tests
uv run pytest tests/ -v                           # all tests
uv run pytest tests/ -v -m "unit"                 # unit only
uv run pytest tests/ -v -m "not integration"      # skip integration
uv run pytest tests/ -v -k "test_name_pattern"    # single test

# Database migrations
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head

# Install dependencies
uv sync
uv sync --group dev
```

## Frontend commands

All run from `frontend/`:

```bash
npm run dev              # start Vite dev server on port 3000 (proxies /api to localhost:8000)
npm run build            # type-check + production build
npm run lint             # ESLint (max-warnings 0)
npm run format           # Prettier write
npm run test             # Vitest (jsdom, globals mode)
npm run test:coverage    # Vitest with coverage
npm run type-check       # tsc --noEmit
```

## Architecture: backend

The backend follows a layered architecture with clean separation of concerns. Full details in `backend/docs/architecture.md`.

### Request flow
```
middleware (CORS → Logging → Tenant) → router → API route → Service → Repository → DB
```

### Key layers

- **`src/main.py`** — FastAPI app factory with lifespan (init monitoring, auto-create tables in dev, close DB/Redis on shutdown). Scalar API docs at `/docs`.
- **`src/api/router.py`** — Route aggregation at `/api/v1/`. Add new route modules here.
- **`src/api/deps.py`** — Shared FastAPI dependency injection (tenant extraction, pagination params).
- **`src/core/config.py`** — All settings via `pydantic-settings` from `.env`. Use `get_settings()` (lru_cached singleton) to access.
- **`src/core/exceptions.py`** — `AppException` base with subclasses per error category. Caught by exception handlers in `main.py` → unified `ErrorResponse`.
- **`src/db/base.py`** — ORM base with mixins: `UUIDPrimaryKeyMixin`, `TimestampMixin`, `TenantIsolationMixin`, `SoftDeleteMixin`. All domain models inherit `BaseModel`.
- **`src/db/repository.py`** — Generic `BaseRepository[ModelType]` with standard CRUD. Takes model class + session.
- **`src/middleware/tenant.py`** — Tenant isolation middleware. When `MULTI_TENANT_ENABLED=false`, all records use `tenant_id="default"`.
- **`src/models/domain/`** — SQLAlchemy ORM models (persistence only, no business logic).
- **`src/models/schemas/`** — Pydantic request/response schemas. `APIResponse[T]` wraps all responses: `{success, code, message, data}`.
- **`src/services/`** — Business logic classes. Receive `AsyncSession`, create Repository internally. No logic in routes.
- **`src/agents/`** — LangGraph-based agent system. `BaseAgent` defines lifecycle, `graph.py` has the ReAct graph, `tools.py` has tool definitions.
- **`src/llm/`** — LLM provider factory (DeepSeek / OpenAI / Anthropic), callbacks.
- **`src/vectorstore/`** — Abstract vector store interface + ChromaDB implementation.

### Auth (dual-token pattern)

Access tokens are short-lived JWTs (HS256, 30min). Refresh tokens are random strings (bcrypt-hashed in DB, 7 days). On refresh, the old refresh token is immediately revoked (rotation). Passwords are bcrypt-hashed via `passlib`.

## Architecture: frontend

React 18 + TypeScript + Vite, styled with Tailwind CSS (shadcn/ui pattern).

### Directory map

```
src/
├── api/          # Axios API layer — one file per resource domain
│   └── client.ts # Axios instance with Bearer injection + 401 auto-refresh
├── components/
│   ├── ui/       # shadcn/ui primitives (Button, Card, Dialog, etc.)
│   ├── layout/   # MainLayout (sidebar + header shell), Header, Sidebar
│   ├── common/   # Shared: ErrorBoundary, LoadingSpinner, EmptyState, TokenGauge, etc.
│   └── auth/     # Auth-specific: CaptchaImage
├── hooks/        # Custom hooks (useAuth, useAgents, useConversations, useDebounce, etc.)
├── lib/          # Utilities (cn() = clsx + tailwind-merge) and constants
├── pages/        # Page components — one folder per route
├── routes/       # React Router config (AppRoutes)
├── stores/       # Zustand stores — flat, no nesting
└── types/        # TypeScript type definitions
```

### Key patterns

- **State management**: Zustand with flat stores (auth, ui, agent, tenant). No context-prop drilling.
- **API client** (`src/api/client.ts`): Axios with interceptor that auto-injects Bearer token and handles 401 by attempting token refresh before redirecting to `/login`. Uses an in-flight refresh lock to prevent concurrent 401 storms.
- **Theming**: Two color schemes (Emerald/Amber) × light/dark = 4 modes. Controlled via `data-theme` attribute on `<html>` + `.dark` CSS class. Full spec in `docs/frontend-theme-system.md`.
- **Routing** (`src/routes/index.tsx`): `MainLayout` wraps authenticated routes (dashboard, agents, conversations, tenant). Login/register are public. 404 catch-all.
- **UI primitives** follow shadcn/ui conventions: `cn()` utility, CVA for variants, Radix primitives underneath.

### Path aliases

`@/` maps to `src/` (configured in both `tsconfig.app.json` and `vite.config.ts`).

## Documentation

Project docs live in `docs/` and `backend/docs/`:

| File | Content |
|------|---------|
| `backend/docs/architecture.md` | Complete backend architecture, ER diagram, API routes, auth flow, env vars, design patterns, extension guide |
| `docs/frontend-theme-system.md` | Emerald/Amber dual-theme CSS custom properties spec |
| `docs/tenant-management.md` | Tenant dashboard page spec: charts, token usage, component breakdown |

The `docs/*.md` files are the "source of truth" for architecture — update them alongside code changes per the project's MD-driven development approach.
