# MVP — Agent Shopping Conversationnel Universel
**Durée : 6 semaines** (semaines 3-8)
**Objectif :** Assistant complet, prêt à être intégré chez un vrai client, avec tous les outils transactionnels et l'architecture universelle.

## Semaine 3 — Architecture stateless + JWT
### Backend
- Remplacement API key → validation JWT :
  - `python-jose` + JWKS endpoint client
  - Extraction `sub` + `tenant_id` + `user_context` du JWT
- Suppression DynamoDB (on ne stocke plus rien)
- Chaque requête transporte `history[]` et `user_context` dans le payload
- Fallback : si pas de JWT, mode "guest" (token éphémère généré côté widget)

### Config tenant
- SSM Parameter Store : `/agent-shopping/tenants/{tenant_id}/*`
- Champs : `api_base_url`, `api_auth_header`, `api_auth_value_ssm`, mapping endpoints

## Semaine 4 — Tous les outils
### Outils à implémenter
| Outil | Appelle API | Statut |
|---|---|---|
| `rechercher_produits` | GET /products/search | Existant |
| `details_produit` | GET /products/{id} | Existant |
| `verifier_stock` | GET /products/{id}/stock | Existant |
| `historique_client` | GET /users/{id}/orders | Nouveau |
| `comparer_produits` | Aggrège plusieurs `details_produit` | Nouveau |
| `ajouter_panier` | POST /cart | Nouveau |
| `passer_commande` | POST /orders | Nouveau |
| `suivre_commande` | GET /orders/{id} | Nouveau |

### Adaptateur client générique
- Lambda `adapter.py` :
  - Prend `{endpoint_config, tool_name, params}`
  - Construit l'URL, ajoute l'auth
  - Nettoie la réponse : plat, résumé, max 2000 chars
  - Timeout : 5s (avec retry 1x)
  - Gère les erreurs : 4xx → message user-friendly, 5xx → "service temporairement indisponible"

### Sécurité transactionnelle
- `passer_commande` exige param `confirmed: true`
- Rate limit : 3 appels/min/tenant pour les outils transactionnels
- Validation backend : quantité max = 99, prix < 10 000€
- Log métrique : `{tool: "passer_commande", success: bool, latency: int}`

## Semaine 5 — Widget final `<agent-shopping>` v1
### Features
- Shadow DOM isolation complète
- Configuration via attributs HTML :
  - `tenant-id`, `api-url`, `primary-color`, `position`
  - `lang="fr"` (évolutif)
- Auth JWT via `assistant.setAttribute('token', jwt)`
- Mode guest si pas de JWT
- Confirmation commande : popup UI "Confirmez-vous la commande de X pour Y € ?"
- Responsive (mobile + desktop)
- État de chargement (spinner) + message d'erreur si API down
- Fallback : si l'API répond pas → afficher "Service indisponible" + email contact
- < 40 KB gzippé

### Build
- Webpack minimal (ou esbuild) → `dist/agent-shopping.js`
- CDN : `https://cdn.agent-shopping.dev/widget/v1/agent-shopping.js`

## Semaine 6 — Streaming + Qualité
### Streaming
- WebSocket API Gateway
- Connection établie à l'ouverture du widget, fermée après 5 min d'inactivité
- Délai max avant premier token : 2s
- Cache sémantique : OpenSearch, clé = hash de `{message, history_summary}`, TTL = 24h

### Prompts
- Prompt système version 1 (français, ton conseiller)
- Haiku pour fast-path : "bonjour", "merci", "au revoir" (détection par classification rapide)
- Sonnet pour tout le reste
- Pas d'A/B encore (V1)

### Monitoring
- Métriques CloudWatch :
  - `latency_ms` (p50, p95, p99)
  - `tool_call_count` par outil
  - `session_length` (nb messages)
  - `error_rate`
- Dashboard CloudWatch basique
- Alarme : error_rate > 5% sur 5 min → SNS → email

## Semaine 7 — Intégration réelle + Tests E2E
- Test avec un vrai client pilote :
  - Configurer son tenant
  - Brancher sur ses API
  - Tester 20 scénarios
- Ajustements adaptateur si besoin
- Tests de charge : 50 conversations simultanées (artillery)

## Semaine 8 — Buffer + Production
- Documentation intégration client (README)
- Finalisation déploiement (SAM / CDK)
- WAF + rate limiting final
- Mise en prod soft (1 client, monitoring renforcé)

## Livrables MVP
- `lambda/*.py` — handler, adapter, validation JWT
- `widget/agent-shopping.js` — Web Component final
- `infra/cdk/` — infrastructure as code
- `scripts/seed-catalog.py` — version améliorée
- `docs/INTEGRATION.md` — guide d'intégration client
- `config/tenants/` — template de configuration tenant
- `tests/` — tests unitaires + E2E

## Tests de validation MVP
- [ ] 8 outils fonctionnent avec l'API mock
- [ ] JWT validation OK (valide, expiré, invalide, guest)
- [ ] Widget fonctionne dans React, Vue, HTML statique, Angular
- [ ] Confirmation UI avant commande
- [ ] Latence < 4s (p95)
- [ ] Cache sémantique répond en < 1s
- [ ] Pas de PII dans les logs
- [ ] Test de charge : 50 conversations simultanées sans erreur
