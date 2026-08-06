# Common Ground & Project Guidelines

**Project:** EasyBits (Backend Focus)
**Last Updated:** 2026-08-06

## 1. Database Tech Stack & Migration Strategy
- **Supabase (PostgreSQL) is the sole database:** We do not use ORMs like SQLAlchemy; we use the Supabase Python client to interact directly with the DB. [ESTABLISHED]
- **Migration Strategy:** Schema changes are managed via plain SQL files in `supabase/migrations/` and applied manually or via Supabase CLI. [WORKING]

## 2. API Architecture, Endpoints, & Routing Design
- **FastAPI Core:** The API is built entirely on FastAPI using `async def` route handlers. [ESTABLISHED]
- **Repository Pattern:** Database interactions are abstracted into a repository layer (`app/db/repositories/`) to separate business logic from data access. [ESTABLISHED]
- **Type Safety:** We enforce Python 3.11+ type hints globally (`list[str]`, `X | None`) as per the `python-pro` skill. [WORKING]

## 3. Data Flow Pipelines & Core Business Logic
- **LangGraph Orchestration:** Complex, multi-step agentic workflows (product extraction, cross-checking, review) are modeled as state graphs using LangGraph. [ESTABLISHED]
- **Async I/O:** All external calls (scraping via Playwright/Firecrawl, Supabase queries, LLM calls) must utilize `asyncio` to prevent blocking the event loop. [ESTABLISHED]
- **Adaptive Input Parsing:** The system accepts 7 core columns from CSVs and dynamically absorbs any extra WooCommerce columns as user overrides. [OPEN]

## 4. Security, CORS, & Environment Variables
- **Authentication:** We use a Shared Secret (`APP_AUTH_SECRET`) exchanged for a short-lived JWT Bearer token. [ESTABLISHED]
- **Configuration Management:** Environment variables are strictly parsed and validated using Pydantic's `BaseSettings`. [ESTABLISHED]

## 5. Server Verification & Test Execution Commands
- **Testing Standard:** Tests are written using `pytest` and `pytest-asyncio`. A >90% coverage threshold is targeted for new code. [WORKING]
- **Test Execution:** Run unit tests via `python -m pytest tests/unit -q`. [ESTABLISHED]
- **Validation:** Code is strictly linted using `ruff` and type-checked using `mypy --strict`. [WORKING]
