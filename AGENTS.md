# agent-shopping — Agent instructions

## Dev commands (Makefile)
- `make install` — pip install dev deps + pre-commit hooks
- `make lint` — ruff check + ruff format --check (line-length 100)
- `make typecheck` — mypy strict mode (disallow_untyped_defs, warn_return_any)
- `make test` — pytest tests/ -v --cov=lambda/ --cov-report=term-missing
- `make format` — ruff format lambda/ scripts/ tests/
- `make build` — runs test → lint → typecheck, then packages Lambda + widget
- `make e2e` — `scripts/test-e2e.sh smoke` (Artillery, needs docker compose up)
- `make docker-build` / `make docker-push` — build + push Lambda image to GHCR
- `make deploy-widget` — upload `widget/dist/` to S3, invalidate CloudFront

Gate before PR: `make lint typecheck test` — all three must pass.

## Local dev
```bash
make install
docker compose up    # lambda (9000), opensearch (9200), widget-nginx (8080)
```
Environment from `.env.example` — set `MOCK_API=true` for offline dev (no AWS calls).
The adapter reads `api/mock-catalog.json` when `base_url` is empty.
RAG silently no-ops when `MOCK_API=true` (OpenSearch client returns `None`).

## RAG seeding
```bash
docker compose up -d opensearch
python scripts/seed-opensearch.py
```

## Infrastructure (CDK)
```bash
cd infra/cdk && pip install -r requirements.txt
cdk bootstrap   # one-time per account/region
cdk deploy      # VPC + Lambda Docker + API Gateway HTTP + WAF + OpenSearch SS + SSM + CloudWatch
```
CDK builds the Lambda Docker image from root `Dockerfile` during deploy.

## Project structure
- **Not a pip-installable package** — no `[build-system]` in any pyproject.toml. Lambda deploys as Docker image, widget is standalone.
- **Dual pyproject.toml**: root `pyproject.toml` is mypy-only (avoids tool conflicts); `lambda/pyproject.toml` has all real config (ruff, mypy strict, pytest).
- **Widget** is a vanilla Web Component built with esbuild (`npm run build` in `widget/`). Not part of the Python backend.

## Architecture
- **Auth** `lambda/auth.py` — JWT validation via JWKS (RS256); guest fallback with `mode=limited`
- **Lambda** `lambda/handler.py` — Bedrock Claude 3.5 Sonnet orchestrator (Claude 3 Haiku for fast-path greetings). Lazy boto3 clients everywhere (`_bedrock_client()`, `_ssm_client()`, `_cw_client()`). Max message length: 2000 chars. Max tool turns: 3 (plus 3000ms Lambda timeout guard).
- **Adapter** `lambda/adapter.py` — translates Bedrock tool calls to client REST APIs. `confirmed=True` required for `ajouter_panier` and `passer_commande`. Rejects non-HTTPS URLs when `base_url` is set.
- **RAG** `lambda/rag.py` — Titan Embeddings v2 → OpenSearch k-NN. LRU + TTL caching.
- **Tracing** `lambda/tracing.py` — LangFuse optional (silently no-ops without env vars)
- **Widget** `widget/agent-shopping.js` — vanilla Web Component (Shadow DOM), ~40KB, zero runtime deps
- All prompts and responses are in **French**

## Testing quirks
- **Run from project root only**: `tests/conftest.py` mutates `sys.path` with `../lambda`. Running pytest from another directory breaks imports. Always use `make test` or run from `agent-shopping/`.
- All external services (SSM, Bedrock, OpenSearch, LangFuse) are mocked. Lazy boto3 clients make this safe — never define a client at module level.
- Adapter uses `catalog_path` parameter for the mock catalog (no `/var/task/` assumption).
- JWT tests generate real RSA key pairs via `cryptography.hazmat`.
- Single test: `pytest tests/test_handler.py::TestIsFastPath -v`

## Code conventions
- **Python 3.12**, strict mypy, no `Any` in signatures, no `# type: ignore`
- No comments in code (must be self-documenting)
- Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`
- Branches: `main` (prod, protected), `develop` (integration, protected), `feat/*`, `fix/*`, `chore/*`
- PRs merge into `develop`, then `develop` → `main` triggers CD
- Pre-commit hooks: ruff (with --fix), mypy, detect-secrets, trailing-whitespace, eof-fixer
- Detect-secrets baseline at `.secrets.baseline`

## CI/CD
- **CI** (push to `develop`/`feat/*`/`fix/*`/`chore/*` or PR): lint → typecheck → test → docker build + smoke test (Artillery)
- **CD** (push to `main`): CI → docker push to ghcr.io with semver + latest → `cdk deploy` → widget deploy to S3 + CloudFront
- Dependabot: weekly bumps for pip (`lambda/`), GitHub Actions (`/`), Docker (`/`)
