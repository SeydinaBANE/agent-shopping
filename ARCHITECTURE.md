# Architecture — Agent Shopping

## Diagramme de flux

```
┌─────────────────────────────────────────────────────────┐
│                  Site Client                            │
│  ┌──────────────────────────────────────────────────┐   │
│  │ <agent-shopping> Web Component                   │   │
│  │  • Shadow DOM                                    │   │
│  │  • Stocke history[] en mémoire                   │   │
│  │  • Affiche confirmation UI avant commande        │   │
│  └────────────┬─────────────────────────────────────┘   │
│               │ JWT (auth client)                       │
│               ▼                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Backend Client (API REST existante)              │   │
│  │  • Produits, stock, panier, commandes            │   │
│  └──────────────────────────────────────────────────┘   │
└──────────┬──────────────────────────────────────────────┘
           │ HTTPS
           ▼
┌──────────────────────────────────────────────────────────┐
│               AWS — Ekkiden Platform                     │
│                                                          │
│  API Gateway (REST + WebSocket)                          │
│    ├─ Auth : JWT → JWKS endpoint client                  │
│    ├─ Rate limit : 10 req/s par user, 50 req/s par tenant│
│    └─ WAF : SQL injection, XSS, prompt patterns          │
│          │                                               │
│          ▼                                               │
│  Lambda (orchestrateur)                                  │
│    ├─ Valide JWT, extrait tenant_id + user_context       │
│    ├─ Récupère config tenant (SSM)                       │
│    ├─ Choisit Haiku (fast) ou Sonnet (complet)          │
│    ├─ Vérifie cache sémantique (OpenSearch)              │
│    └─ Appelle Bedrock Agent                              │
│          │                                               │
│          ▼                                               │
│  Bedrock Agent (Claude 3.5)                              │
│    ├─ Prompt système tenant                               │
│    ├─ Reasoning + tool selection                          │
│    └─ Tool calls → Lambda adaptateur                     │
│          │                                               │
│          ▼                                               │
│  Lambda adaptateur par tenant                            │
│    ├─ Construit URL depuis config tenant                 │
│    ├─ Appelle API client avec timeout 5s                 │
│    ├─ Nettoie réponse (max 2000 chars, plat)             │
│    └─ Retourne à Bedrock Agent                           │
│                                                          │
│  OpenSearch Serverless (1 index/tenant)                  │
│    ├─ RAG : embeddings du catalogue client               │
│    └─ Cache sémantique                                   │
│                                                          │
│  SSM Parameter Store                                     │
│    └─ Configurations par tenant (endpoints, auth, brand) │
│                                                          │
│  CloudWatch + LangFuse                                   │
│    └─ Métriques anonymes (latence, outils, erreurs)      │
└──────────────────────────────────────────────────────────┘
```

## Séquence détaillée (commande)

```
User: "ajoute ce pull noir à mon panier"
  → Widget envoie {message, history, user_context, tenant_id}
  → API Gateway valide JWT
  → Lambda choisit Sonnet (action transactionnelle)
  → Cache miss (première fois)
  → Bedrock Agent reçoit prompt + history
  → Agent appelle rechercher_produits("pull noir")
      → Lambda adaptateur → GET /api/products/search?q=pull+noir
      → Retourne [{id: "P123", name: "Pull noir", price: 49.99, stock: 12}]
  → Agent appelle ajouter_panier("P123", qty: 1)
      → Lambda vérifie "confirmed" (pas encore → demande)
      → Agent répond "Je peux ajouter ce pull noir à votre panier pour 49,99€ ?"
  → Widget affiche la réponse + bouton "Confirmer"
  → User clique "Confirmer"
  → Widget envoie {message: "CONFIRM_COMMAND", intent: "ajouter_panier", params: {...}}
  → Agent appelle ajouter_panier avec confirmed=true
      → POST /api/cart {user_id, product_id: "P123", quantity: 1}
      → Succès
  → Agent: "C'est fait ! Le pull noir est dans votre panier."
```

## Modèle de données (aucune donnée persistée)

Seule donnée stockée = **configuration tenant** dans SSM :

```json
{
  "tenant_id": "string",
  "name": "string",
  "public_key_jwks_uri": "string",
  "api_base_url": "string",
  "api_auth_header": "string",
  "api_auth_value_ssm": "string (path to secret)",
  "endpoints": {
    "search_products": "string",
    "product_detail": "string",
    "check_inventory": "string",
    "user_history": "string",
    "add_to_cart": "string",
    "place_order": "string",
    "track_order": "string"
  },
  "brand": {
    "primary_color": "string",
    "logo_url": "string",
    "name": "string"
  },
  "llm_config": {
    "model": "claude-3-5-sonnet|claude-3-haiku",
    "temperature": 0.3,
    "max_tokens": 1024
  }
}
```

## Stratégie de déploiement
- Infrastructure : AWS CDK (Python)
- Lambda : SAM / Docker image
- Widget : esbuild → S3 + CloudFront CDN
- CI/CD : GitHub Actions → SAM deploy
