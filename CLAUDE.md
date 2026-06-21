# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` is the authoritative, detailed source for this project. Read it before non-trivial work — this file is the quick map. (The repo root `../CLAUDE.md` describes the wider `ekk/` workspace; this project develops on the `develop` branch.)

## What this is

Agent Shopping — an agentic e-commerce chatbot with **zero user-data storage**. An AWS Bedrock (Claude 3.5) orchestrator understands natural language, retrieves catalog context via OpenSearch RAG, and executes business actions (cart, order, tracking) through the client's REST APIs. Shipped as a vanilla Web Component widget. All prompts and responses are in **French**.

## Commands

Run everything from the project root (`agent-shopping/`).

```bash
make install      # pip install lambda/requirements-dev.txt + pre-commit hooks
make lint         # ruff check + ruff format --check (lambda/ scripts/ tests/)
make typecheck    # mypy strict (lambda/ scripts/ tests/)
make test         # pytest -v --cov=lambda/ --cov-report=term-missing
make build        # test → lint → typecheck, then build widget + package Lambda
make e2e          # scripts/test-e2e.sh smoke (Artillery; needs docker compose up)
make format       # ruff format
```

**Gate before any PR: `make lint typecheck test` must all pass.** `make build` is the full pre-push gate (note it implies the three checks plus packaging).

Single test: `pytest tests/test_handler.py::TestIsFastPath -v`

Local dev: `make install` then `docker compose up` → lambda (9000), opensearch (9200), widget-nginx (8080). Set `MOCK_API=true` (default in `.env.example`) for fully offline dev — no AWS calls; the adapter reads `api/mock-catalog.json` and RAG silently no-ops.

RAG seeding: `docker compose up -d opensearch && python scripts/seed-opensearch.py`

Infra: `cd infra/cdk && pip install -r requirements.txt && cdk deploy` (builds the Lambda Docker image from the root `Dockerfile`).

## Architecture

Request flow: widget → API Gateway → Lambda orchestrator → (RAG retrieval + Bedrock tool-calling loop → adapter → client REST APIs) → response.

- **`lambda/handler.py`** — orchestrator. Bedrock Claude 3.5 Sonnet, with Claude 3 Haiku as a fast-path for greetings (`is_fast_path`). `MAX_TOOL_TURNS = 3`, plus a 3000ms timeout guard; max message length 2000 chars.
- **`lambda/adapter.py`** — translates Bedrock tool calls into the client's REST APIs. `confirmed=True` is required for `ajouter_panier` and `passer_commande`. Rejects non-HTTPS URLs when `base_url` is set; falls back to the mock catalog (via `catalog_path`) when `base_url` is empty.
- **`lambda/auth.py`** — JWT validation via JWKS (RS256); guest fallback yields `mode=limited`. Multi-tenant isolation.
- **`lambda/rag.py`** — Titan Embeddings v2 → OpenSearch k-NN, with LRU + TTL caching.
- **`lambda/tracing.py`** — optional LangFuse; silently no-ops without env vars.
- **`widget/agent-shopping.js`** — vanilla Web Component (Shadow DOM), SSE streaming, ~40KB, zero runtime deps. Built with esbuild (`npm run build` in `widget/`). Not part of the Python backend.
- **`infra/cdk/`** — AWS CDK: VPC, Lambda (Docker), API Gateway HTTP, WAF, OpenSearch Serverless, SSM, CloudWatch.

## Key conventions & gotchas

- **Not a pip-installable package** — no `[build-system]`. Lambda deploys as a Docker image; widget is standalone.
- **Dual pyproject.toml**: root `pyproject.toml` is mypy-only (avoids tool conflicts); `lambda/pyproject.toml` holds the real ruff/mypy-strict/pytest config.
- **Always run tests from the project root** — `tests/conftest.py` mutates `sys.path` with `../lambda`; running pytest elsewhere breaks imports.
- **Lazy boto3 clients everywhere** (`_bedrock_client()`, `_ssm_client()`, `_cw_client()`) — never define a client at module level. This keeps all external services (SSM, Bedrock, OpenSearch, LangFuse) mockable in tests. JWT tests generate real RSA key pairs via `cryptography.hazmat`.
- **Typing**: Python 3.12, mypy strict, no bare `Any` in signatures, no `# type: ignore` without a documented reason. No comments in code — it must be self-documenting.
- **Commits / branches**: Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`). Branch off `develop`; PRs merge into `develop`, then `develop` → `main` triggers CD. Both `main` and `develop` are protected.
- Pre-commit runs ruff (`--fix`), mypy, detect-secrets (baseline `.secrets.baseline`), trailing-whitespace, eof-fixer.

## CI/CD

- **CI** (push to `develop`/`feat/*`/`fix/*`/`chore/*` or PR): lint → typecheck → test → docker build + Artillery smoke test.
- **CD** (push to `main`): CI → docker push to `ghcr.io/ekkiden/agent-shopping` (semver + latest) → `cdk deploy` → widget deploy to S3 + CloudFront.
