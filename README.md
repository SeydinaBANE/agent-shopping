# Agent Shopping

[![CI](https://github.com/ekkiden/agent-shopping/actions/workflows/ci.yml/badge.svg)](https://github.com/ekkiden/agent-shopping/actions/workflows/ci.yml)
[![CD](https://github.com/ekkiden/agent-shopping/actions/workflows/cd.yml/badge.svg)](https://github.com/ekkiden/agent-shopping/actions/workflows/cd.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-blue)](https://ghcr.io/ekkiden/agent-shopping)
[![Python](https://img.shields.io/badge/python-3.12-blue?logo=python)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![Coverage](https://img.shields.io/badge/coverage-89%25-brightgreen)](https://github.com/SeydinaBANE/agent-shopping)

**Assistant IA conversationnel pour le e-commerce — zéro stockage de données utilisateur.**

Agent Shopping est un chatbot agentic AWS Bedrock (Claude 3.5) qui comprend le langage naturel, consulte un catalogue RAG via OpenSearch et exécute des actions métier (panier, commande, suivi) via des appels API REST. Livré en Web Component vanilla, sans dépendance npm.

---

## About

| | |
|---|---|
| **Stack** | Python 3.12, AWS Lambda, Bedrock Claude 3.5, OpenSearch, AWS CDK |
| **Agentic** | Tool calling multi-tour, RAG contextuel, routage Haiku/Sonnet |
| **Frontend** | Web Component Shadow DOM, streaming SSE, zéro build |
| **Auth** | JWT/JWKS + guest mode, isolation multi-tenant |
| **Infra** | Docker, AWS CDK (VPC, API GW, WAF, CloudWatch), CI/CD GitHub Actions |
| **Sécurité** | HTTPS-only, XSS-free, pas de stockage utilisateur |

## Quick Start

```bash
make install          # Installe les dépendances
docker compose up     # Lance Lambda + OpenSearch + Widget
```

## Documentation

| Fichier | Description |
|---|---|
| [PROJET.md](PROJET.md) | Vision et architecture globale |
| [POC.md](POC.md) | Plan du POC (2 semaines) |
| [MVP.md](MVP.md) | Plan du MVP (6 semaines) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture détaillée |
| [SECURITY.md](SECURITY.md) | Sécurité et RGPD |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribuer au projet |

## Licence

MIT — voir [LICENSE](LICENSE).
