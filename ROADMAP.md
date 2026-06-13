# Roadmap — Agent Shopping Conversationnel

## Phase 0 — Données synthétiques (1 sem.)
- Génération catalogue + QA
- API mock
- Validation des formats

## Phase 1 — POC (2 sem.)
- Lambda + Bedrock Agent (3 outils)
- Web Component v0
- Démo 3 scénarios
- ✅ Go/No-Go : latence < 5s, réponses pertinentes, widget compatible

## Phase 2 — MVP (6 sem.)
- JWT auth + architecture stateless
- 8 outils + adaptateur client
- Web Component v1 + CDN
- Streaming + cache sémantique
- Monitoring + alerting
- Test réel client pilote
- Documentation intégration
- ✅ Go/No-Go : latence < 4s p95, taux erreur < 2%, 1 client live

## Phase 3 — V1 (4 sem. après MVP)
- A/B testing de prompts
- Self-service console admin (onboarding autonome)
- Dashboard QuickSight (métriques clients)
- Traduction multilingue (EN + DE)
- Mode voice (Amazon Lex)
- Tests de charge : 500 conversations simultanées
- ✅ OK : prêt pour scale commercial

## Phase 4 — Scale (ongoing)
- Multi-modèle (Mistral, Llama via Bedrock)
- Fine-tuning sur données client (opt-in)
- Version enterprise (on-prem / VPC dédié)
