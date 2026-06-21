# Faille — Agent Shopping

## Résumé exécutif

| # | Faille | Sévérité | Status |
|---|--------|-----------|--------|
| 1 | Pas de validation HMAC sur les webhooks sortants → SSRF potentiel | **Moyenne** | À corriger |
| 2 | Fallback guest silencieux si JWKS endpoint injoignable | **Moyenne** | Accepté (scope limité) |
| 3 | `ensure_ascii=False` sur les outputs LLM → XSS potentiel dans le widget | **Moyenne** | À corriger |
| 4 | Aucune limite de taille sur l'entrée `message` → attaque par déni | **Basse** | À corriger |
| 5 | `cloudwatch:PutMetricData` sur `*` → exfiltration de données possible | **Basse** | À corriger |
| 6 | Pas de COOP/COEP sur le CDN → widget vulnérable à l'isolation cross-origin | **Basse** | À corriger |

---

## 1. SSRF via webhooks sortants

**Type** : Server-Side Request Forgery (SSRF)
**Sévérité** : **Moyenne** (CVSS 4.3)
**Où** : `lambda/adapter.py:104-107`

### Description
Les appels API vers le client sont des requêtes HTTP sortantes vers une URL configurée dans SSM (`api_base_url`). Aucune validation n'est effectuée sur :
- Le schéma (http vs https)
- L'hôte (localhost, IP interne, metadata AWS)
- Le port

Si un attaquant modifie `api_base_url` dans SSM (via une faille IAM ou un admin malveillant), l'agent peut envoyer des requêtes vers des ressources internes AWS (ex: `http://169.254.169.254/latest/meta-data/`).

### Mitigation actuelle
- `api_base_url` est stocké dans SSM Parameter Store (chiffré) et contrôlé par IAM
- Pas de route pour modifier SSM depuis l'extérieur

### Fix
```python
if not base_url.startswith("https://"):
    raise ValueError("Only HTTPS URLs are allowed")
```
Ou ajouter une allowlist de domaines dans le tenant config.

---

## 2. Fallback guest silencieux

**Type** : Authentication bypass partiel
**Sévérité** : **Moyenne** (CVSS 4.0)
**Où** : `lambda/auth.py:116-120`

### Description
Si `extract_user_context()` reçoit un token invalide OU si le JWKS endpoint est injoignable, elle retourne un contexte guest au lieu de rejeter la requête. Cela signifie :
- Un attaquant peut contourner l'auth en saturant le JWKS endpoint (déni → fallback guest)
- Un token expiré est traité comme guest, pas rejeté

Le scope guest n'a pas accès aux transactions (panier/commande) ni aux données client réelles, mais peut :
- Consulter le catalogue (en mock local)
- Démarrer une session
- Voir le RAG s'il est activé

### Mitigation actuelle
- Mode guest = catalogue en cache local, pas d'appels API client
- Pas d'accès aux endpoints transactionnels

### Fix
- Logger un avertissement distinct en cas de fallback guest sur token invalide
- Optionnel : mode "strict" où un token invalide → 401 (configurable par tenant)

---

## 3. XSS potentiel via `ensure_ascii=False`

**Type** : Cross-Site Scripting (Stored/Reflected)
**Sévérité** : **Moyenne** (CVSS 5.4)
**Où** : `lambda/handler.py:196,210,251` + `widget/agent-shopping.js`

### Description
`json.dumps(..., ensure_ascii=False)` préserve les caractères Unicode, mais ne sanitize pas les chaînes. Si le LLM génère du HTML/JavaScript (volontairement ou par injection), le widget qui affiche le texte avec `innerHTML` (Shadow DOM) exécute ce code.

En pratique :
- Le prompt système demande explicitement du texte simple
- Le Shadow DOM du widget isole le style mais pas l'exécution de scripts
- Un prompt injection réussi pourrait faire générer `<img src=x onerror=alert(1)>` au LLM

### Mitigation actuelle
- Prompt système : "Réponds toujours en texte simple"
- WAF AWS filtre les patterns d'injection côté entrée
- Shadow DOM : certains navigateurs isolent les scripts

### Fix
```javascript
// Dans le widget, remplacer innerHTML par textContent
this.shadowRoot.getElementById("response").textContent = text;
```
Ou ajouter un DOMPurify sur la sortie LLM avant affichage.

---

## 4. Aucune limite de taille sur l'entrée `message`

**Type** : Denial of Service
**Sévérité** : **Basse** (CVSS 3.1)
**Où** : `lambda/handler.py:422`

### Description
Le champ `message` peut contenir n'importe quelle taille (jusqu'à 6 Mo via API Gateway). Un message de 10 000 tokens :
- Consomme inutilement des tokens Bedrock (coût)
- Retarde la réponse pour les autres utilisateurs (cold start + compute)
- Peut faire timeouter le Lambda sur des messages très longs

### Mitigation actuelle
API Gateway a une limite de 6 Mo par body (limite AWS).

### Fix
```python
if len(message) > 2000:
    return {"statusCode": 400, "body": json.dumps({"error": "Message trop long (max 2000 caractères)"})}
```

---

## 5. `cloudwatch:PutMetricData` sur `*`

**Type** : Privilège excessif
**Sévérité** : **Basse** (CVSS 2.1)
**Où** : `infra/cdk/stacks/agent_shopping_stack.py:120-123`

### Description
La politique IAM autorise `cloudwatch:PutMetricData` sur toutes les ressources (`"*"`). Une Lambda compromise pourrait :
- Émettre de fausses métriques pour masquer une attaque
- Épuiser le quota CloudWatch (coût)
- Altérer des dashboards

### Mitigation actuelle
- `PutMetricData` est non-destructif (ne peut que créer, pas modifier/supprimer)
- La Lambda est dans un VPC privé, pas d'accès internet sauf via NAT

### Fix
```python
"resources": [f"arn:aws:cloudwatch:{self.region}:{self.account}:metric-stream/*"]
```
Ou supprimer la ressource (seule `*` est acceptée par CloudWatch pour `PutMetricData`, c'est une limitation AWS → laisser `*` et documenter).

---

## 6. Absence d'en-têtes COOP/COEP sur le CDN

**Type** : Cross-Origin Isolation
**Sévérité** : **Basse** (CVSS 2.6)
**Où** : `infra/cdk/stacks/agent_shopping_stack.py:445`

### Description
Le widget est servi via CloudFront sans en-têtes `Cross-Origin-Opener-Policy` ni `Cross-Origin-Embedder-Policy`. Combiné avec `CORS: *` sur l'API Gateway, un site malveillant pourrait :
- Intégrer le widget dans une iframe
- Intercepter ou manipuler les messages postMessage si le widget les utilise

### Mitigation actuelle
- Le widget utilise Shadow DOM (isolation de style)
- Les tokens JWT sont générés par le site client, pas stockés dans le widget
- Pas de `postMessage` utilisé par le widget

### Fix
```python
distribution = cloudfront.Distribution(
    ...
    default_behavior=cloudfront.BehaviorOptions(
        response_headers_policy=cloudfront.ResponseHeadersPolicy(
            custom_headers_behavior=cloudfront.HeadersBehavior(
                custom_headers=[
                    cloudfront.CustomHeader(name="Cross-Origin-Opener-Policy", value="same-origin"),
                    cloudfront.CustomHeader(name="Cross-Origin-Embedder-Policy", value="require-corp"),
                ]
            ),
        ),
    ),
)
```

---

## Analyse des risques acceptés

| Risque | Justification |
|--------|---------------|
| Guest fallback sur JWKS down | Critique de garder le service disponible même si l'auth client est dégradé ; le scope guest est limité |
| CORS `*` sur API Gateway | L'API est conçue pour être appelée depuis n'importe quel domaine client ; l'auth est gérée par JWT |
| Pas de rate limiting par tenant | Le rate limiting IP-based est suffisant pour le MVP ; sera ajouté par tenant en V1 |
| SSM paramètres non versionnés | Les tenants sont déployés via CDK, les paramètres sont gérés comme du code |
| `PutMetricData` sur `*` | CloudWatch n'accepte pas de ressource spécifique pour cette action ; limitation AWS |

## Procédure de signalement

Toute faille découverte doit être :
1. Documentée dans ce fichier avec sévérité CVSS
2. Créée comme issue GitHub avec label `security`
3. Corrigée dans une branche `fix/sec-*`
4. Reviewée par au moins une autre personne
5. Déployée en urgence si sévérité ≥ Haute
