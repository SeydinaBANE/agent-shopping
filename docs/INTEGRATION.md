# Guide d'intégration — Agent Shopping

## Vue d'ensemble

Le `<agent-shopping>` est un Web Component vanilla à embarquer sur n'importe quel site e-commerce (React, Vue, Angular, Shopify, HTML statique). Aucune dépendance, ~40KB.

## 1. Installation

```html
<!-- Version CDN (recommandée) -->
<script src="https://cdn.agent-shopping.dev/widget/v1/agent-shopping.js"></script>

<!-- Version auto-hébergée -->
<script src="/chemin/vers/agent-shopping.js"></script>
```

## 2. Usage de base

```html
<agent-shopping
  tenant-id="mon-client"
  api-url="https://api.agent-shopping.dev"
  primary-color="#6C5CE7"
  position="bottom-right"
></agent-shopping>
```

Un bouton flottant apparaît en bas à droite. Au clic, la fenêtre de chat s'ouvre.

## 3. Configuration

| Attribut | Type | Défaut | Description |
|---|---|---|---|
| `tenant-id` | string | `"default"` | Identifiant tenant fourni par Ekkiden |
| `api-url` | string | `"https://api.agent-shopping.dev"` | URL de l'API Gateway |
| `primary-color` | string | `"#6C5CE7"` | Couleur primaire (hex) |
| `position` | string | `"bottom-right"` | `bottom-right`, `bottom-left` |
| `lang` | string | `"fr"` | Langue (clients aujourd'hui) |
| `token` | string | `null` | JWT d'authentification (optionnel) |

Les attributs sont dynamiques (mis à jour via `setAttribute`).

## 4. Authentification JWT

### Génération côté client

Le client signe un JWT avec sa **clé privée**. La clé publique correspondante est exposée via un endpoint JWKS.

#### Structure du JWT

```json
{
  "sub": "user-123",
  "tenant_id": "mon-client",
  "user_context": {
    "client_id": "user-123",
    "email_hash": "a1b2c3d4..."
  },
  "exp": 1893456000,
  "iat": 1893452400
}
```

| Champ | Description |
|---|---|
| `sub` | Identifiant utilisateur côté client |
| `tenant_id` | Doit correspondre au `tenant-id` du widget |
| `user_context.client_id` | Transmis aux appels API client |
| `user_context.email_hash` | Hash SHA-256 de l'email (anonymisation) |

#### Exemple (Node.js)

```js
const jwt = require('jsonwebtoken');

const token = jwt.sign(
  {
    sub: 'user-123',
    tenant_id: 'mon-client',
    user_context: {
      client_id: 'user-123',
    },
  },
  process.env.JWT_PRIVATE_KEY,
  {
    algorithm: 'RS256',
    expiresIn: '15m',
  }
);
```

### Passage du token au widget

```html
<agent-shopping id="assistant" tenant-id="mon-client"></agent-shopping>

<script>
  const assistant = document.getElementById('assistant');
  assistant.token = jwtToken;
  // Alternative : assistant.setAttribute('token', jwtToken);
</script>
```

### Mode guest (sans JWT)

Si aucun token n'est fourni, le widget fonctionne en mode limité (consultation catalogue uniquement).

## 5. Onboarding tenant

Fournissez à Ekkiden un fichier de configuration :

```json
{
  "tenant_id": "mon-client",
  "name": "Mon Site",
  "public_key_jwks_uri": "https://api.monsite.com/.well-known/jwks.json",
  "api_base_url": "https://api.monsite.com/v3",
  "api_auth_header": "X-Api-Key",
  "api_auth_value_ssm": "/agent-shopping/tenants/mon-client/api-key",
  "endpoints": {
    "search_products": "/products/search",
    "product_detail": "/products/{produit_id}",
    "check_inventory": "/products/{produit_id}/stock",
    "user_history": "/users/{client_id}/orders",
    "add_to_cart": "/cart",
    "place_order": "/orders",
    "track_order": "/orders/{commande_id}"
  },
  "brand": {
    "primary_color": "#6C5CE7",
    "logo_url": "https://monsite.com/logo.png",
    "name": "Mon Site"
  }
}
```

### APIs requises

| Outil | Méthode | Endpoint | Description |
|---|---|---|---|
| `rechercher_produits` | GET | `/products/search?q=...` | Recherche texte |
| `details_produit` | GET | `/products/{id}` | Fiche produit |
| `verifier_stock` | GET | `/products/{id}/stock?quantite=...` | Disponibilité |
| `historique_client` | GET | `/users/{id}/orders` | Commandes passées |
| `ajouter_panier` | POST | `/cart` | Ajout au panier |
| `passer_commande` | POST | `/orders` | Validation commande |
| `suivre_commande` | GET | `/orders/{id}` | Suivi livraison |

Toutes les APIs doivent retourner du JSON. Timeout attendu : < 5s.

### Contraintes de sécurité

- `ajouter_panier` et `passer_commande` nécessitent une double confirmation (UI widget + paramètre `confirmed=true`)
- Ne jamais exposer de PII dans les réponses API (pas de nom, email, adresse en clair)
- Rate limit : 3 appels/min par utilisateur pour les actions transactionnelles

## 6. Personnalisation

### Couleurs

```html
<agent-shopping primary-color="#FF6B6B"></agent-shopping>
```

### Positions

```html
<agent-shopping position="bottom-left"></agent-shopping>
```

### Changement dynamique

```js
document.querySelector('agent-shopping')
  .setAttribute('primary-color', '#00B894');
```

## 7. Sécurité

| Mesure | Détail |
|---|---|
| JWT | Validation via JWKS endpoint client, expiration 15min |
| WAF | Rate limiting + SQL injection / XSS / prompt injection |
| Double confirmation | L'utilisateur voit une modale avant toute action panier/commande |
| Zero storage | Aucune donnée utilisateur persistée chez Ekkiden |
| Logs | Métriques uniquement (latence, outils appelés), pas de PII |

## 8. Limitations

- Pas de streaming WebSocket (V1 à venir)
- Mode guest : consultation catalogue uniquement
- Langue : français uniquement (autres langues en roadmap)
- Pas de mode voice (roadmap V1)
