# Assistant Shopping Conversationnel Universel

## Vision
Un assistant IA conversationnel embeddable dans n'importe quel site e-commerce, sans stockage de données utilisateur côté Ekkiden. L'utilisateur parle en langage naturel, l'assistant comprend, explore le catalogue, exécute des actions (panier, commande).

## Principes fondateurs
- **Zero storage** : aucune donnée utilisateur persistée chez Ekkiden
- **Universel** : Web Component vanilla, fonctionne partout
- **Stateless** : chaque requête contient tout le contexte
- **Tenant-isolé** : index par client, IAM stricte
- **Sécurité d'abord** : double confirmation avant commande (UI, pas LLM)

## Architecture

```
Site Client (React/Vue/Angular/Shopify/HTML brut)
  └── <agent-shopping> Web Component
        │
        ▼
  API Gateway Ekkiden
    ├── JWT validation (clé publique tenant)
    ├── Rate limiting (par tenant + user)
    │
    ▼
  Lambda orchestrateur (stateless)
    ├── Bedrock Agent (Claude 3.5 Sonnet)
    │     ├── Outils → API du client via adaptateur
    │     └── Bedrock Knowledge Base (RAG catalogue)
    │
    ├── OpenSearch Serverless (1 index/tenant)
    │
    └── Parameter Store (config par tenant)

Client Backend (API REST existante)
  └── Produits, stock, panier, commandes
```

## Stack technique
| Composant | Technologie |
|---|---|
| Widget | Web Component vanilla JS (< 40KB gzippé) |
| Auth | JWT signé par le client, validé via JWKS |
| API | API Gateway REST + WebSocket |
| Orchestration | Lambda (Python) |
| LLM | Bedrock Claude 3.5 Sonnet + Haiku (fast-path) |
| RAG | Bedrock Knowledge Base + OpenSearch Serverless |
| Cache sémantique | OpenSearch (réponses pré-générées) |
| Config tenant | SSM Parameter Store |
| Monitoring | CloudWatch + LangFuse (métriques uniquement, pas de PII) |

## Phases
1. **Phase 0** — Données synthétiques + API mock
2. **POC** (2 sem.) — Chat basique + RAG + widget minimal
3. **MVP** (6 sem.) — Assistant complet + outils transactionnels + universel
4. **V1** (10 sem.) — Qualité, monitoring, self-service onboarding

## Risques majeurs
| Risque | Mitigation |
|---|---|
| APIs client incompatibles LLM | Adaptateur par tenant (Lambda traductrice) |
| Prompt injection → commande frauduleuse | Confirmation UI + param `confirmed` + rate limit |
| Latence > 8s | Cache sémantique + Haiku fast-path + pas de streaming |
| Client incapable de générer JWT | Fallback token éphémère + SDK JS |
| Débogage sans PII | Logs métriques uniquement |
