# agent-shopping — Agent instructions

## Dev commands (Makefile)
- `make install` — pip install dev deps + pre-commit hooks
- `make lint` — ruff check + ruff format --check (line-length 100)
- `make typecheck` — mypy strict mode (disallow_untyped_defs, warn_return_any)
- `make test` — pytest tests/ -v --cov=lambda/ --cov-report=term-missing
- `make format` — ruff format lambda/ scripts/ tests/
- `make build` — runs test → lint → typecheck, then packages Lambda + widget

Gate before PR: `make lint typecheck test` — must pass.

## Local dev
```bash
make install
docker compose up    # Lambda (port 9000) + OpenSearch (9200) + Widget (8080)
```

Environment from `.env.example` — `MOCK_API=true` for offline dev (no AWS Bedrock).
The adapter reads `api/mock-catalog.json` when `base_url` is empty.

## RAG seeding
```bash
docker compose up -d opensearch     # start OpenSearch
python scripts/seed-opensearch.py   # embed catalog + index into OpenSearch
```

## Infrastructure (CDK)
```bash
cd infra/cdk
pip install -r requirements.txt
cdk bootstrap   # one-time per account/region
cdk deploy      # deploys VPC + Lambda + API Gateway + WAF + OpenSearch + SSM + CloudWatch
```
CDK builds the Lambda Docker image from `Dockerfile` during deploy.

## Architecture
- **Lambda** `lambda/handler.py` — Bedrock Claude 3.5 orchestrator, stateless, JWT → SSM config → model routing (Haiku for greetings, Sonnet for real queries)
- **Adapter** `lambda/adapter.py` — translates Bedrock tool calls to client REST APIs; `confirmed=True` guardrail on cart/order tools
- **RAG** `lambda/rag.py` — Titan Embeddings v2 → OpenSearch k-NN search; context injected into system prompt for non-fast-path queries
- **Widget** `widget/agent-shopping.js` — vanilla Web Component (Shadow DOM), no build step, no npm, ~40KB
- **Infra** `infra/cdk/` — AWS CDK Python (VPC, Lambda Docker, API Gateway HTTP, WAF, OpenSearch Serverless, SSM, CloudWatch dashboard + alarms)
- All prompts and responses are in **French**

## Testing quirks
- All external services (SSM, Bedrock, OpenSearch) are mocked in tests
- Adapter uses `catalog_path` parameter to read mock catalog (no `/var/task/` needed)
- RAG module uses lazy `boto3.client()` — not initialized at import time, safe for tests
- Run single test: `pytest tests/test_handler.py::TestIsFastPath -v`

## Code conventions
- **Python 3.12**, strict mypy, no `Any` in signatures, no `# type: ignore`
- No comments in code (must be self-documenting)
- Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`
- Branches: `main` (prod, protected), `develop` (integration, protected), `feat/*`, `fix/*`, `chore/*`
- PRs merge into `develop`, then `develop` → `main` triggers CD
- Pre-commit hooks: ruff, mypy, detect-secrets, trailing-whitespace, eof-fixer

## CI/CD
- **CI** (push to `develop`/`feat/*`/`fix/*`/`chore/*` or PR): lint → typecheck → test → docker build + smoke test
- **CD** (push to `main`): CI → docker push to ghcr.io → `cdk deploy` in `infra/cdk/`
- Deploy requires `AWS_ACCOUNT_ID` secret (for bootstrap) + `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
- Dependabot: weekly bumps for pip (lambda), GitHub Actions, Docker
