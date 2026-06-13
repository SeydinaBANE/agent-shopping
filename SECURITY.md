# Security — Agent Shopping Conversationnel

## Principes
- Zero stockage de données utilisateur
- Isolation stricte par tenant
- Defence in depth : UI + API + LLM guardrails

## 1. Authentification
- **JWT** signé par le client (clé publique via JWKS endpoint)
- Contenu : `{sub, tenant_id, user_context, exp, iat}`
- Fallback guest : token éphémère signé par Ekkiden (données limitées)
- Expiration : 15 min, renouvelé côté widget

## 2. Autorisation
- Par tenant : un client ne peut appeler que ses propres outils
- Par utilisateur : extraction du `sub` JWT, utilisé dans les appels API
- Pas d'escalade possible (les outils ne changent pas selon le rôle)

## 3. Prompt injection
- WAF AWS : règles OWASP + patterns connus d'injection
- Guardrails Bedrock : denied topics, sensitive info filter, word filter
- Validation entrée Lambda : max 2000 chars, regex alphanumérique étendue
- Prompt système : instructions de non-déviation renforcées

## 4. Outils transactionnels
- **Double confirmation UI** : le widget affiche une modale avant commande
- Paramètre `confirmed` requis : côté Lambda, pas LLM
- Rate limit : 3 appels/min/transactionnel par user
- Quantité max : 99, prix max : 10 000€

## 5. Isolation tenant
- 1 index OpenSearch par tenant (IAM policy)
- Config tenant verrouillée (SSM, pas accessible via API)
- Logs : champ `tenant_id` mais pas de PII

## 6. Données
- Aucune donnée utilisateur persistée
- Logs : métriques uniquement
- Cache sémantique : key = hash(`{message, history_summary, tenant_id}`), TTL 24h
- Pas de logging du contenu des messages

## 7. Réseau
- API Gateway : TLS 1.2+ uniquement
- Lambda dans VPC (si accès à des ressources internes client)
- OpenSearch : VPC + policy IP restreinte
- Appels API client : via HTTPS uniquement

## Ce qui n'est PAS couvert (responsabilité client)
- Sécurité du JWT côté client (stockage dans localStorage/SecureCookie)
- Auth entre le widget et le backend client (hors de notre périmètre)
- RGPD côté client (collecte des données)
