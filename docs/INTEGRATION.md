# Guide d'intégration — Agent Shopping

## 1. Ajouter le widget à votre site

```html
<!-- 1. Ajouter le script (uniquement si vous n'utilisez pas le CDN) -->
<script src="https://cdn.agent-shopping.dev/widget/v1/agent-shopping.js"></script>

<!-- 2. Ou via CDN -->
<script src="https://cdn.agent-shopping.dev/widget/v1/agent-shopping.js"></script>

<!-- 3. Ajouter le composant -->
<agent-shopping
  tenant-id="votre-tenant-id"
  api-url="https://api.agent-shopping.dev"
  primary-color="#6C5CE7"
  position="bottom-right"
  lang="fr"
></agent-shopping>
```

## 2. Authentification JWT

Votre backend doit générer un JWT signé et le passer au widget :

```javascript
const assistant = document.querySelector('agent-shopping');
assistant.token = jwt; // Votre JWT signé
```

Le JWT doit contenir :
```json
{
  "sub": "user-123",
  "tenant_id": "votre-tenant-id",
  "user_context": {
    "loyalty_tier": "gold",
    "preferences": ["robe", "été"]
  },
  "exp": 1718000000,
  "iat": 1717996400
}
```

**Sans JWT** : le widget fonctionne en mode "guest" (recherche uniquement, pas de commande).

## 3. APIs à exposer

Notre assistant appelle les endpoints suivants sur votre backend :

| Endpoint | Méthode | Description |
|---|---|---|
| `/products/search?q=...` | GET | Recherche produits |
| `/products/{id}` | GET | Détail produit |
| `/products/{id}/stock` | GET | Stock produit |
| `/users/{id}/orders` | GET | Historique client |
| `/cart` | POST | Ajouter au panier |
| `/orders` | POST | Passer commande |
| `/orders/{id}` | GET | Suivi commande |

## 4. Configuration tenant

Contactez-nous pour configurer votre tenant. Nous avons besoin de :
- URL de base de votre API
- Clé d'API ou méthode d'authentification
- Mapping des endpoints (si différents du standard)
- URL de votre JWKS pour la validation JWT

## 5. Personnalisation

```html
<agent-shopping
  tenant-id="mon-shop"
  api-url="https://api.agent-shopping.dev"
  primary-color="#FF6B35"
  position="bottom-left"
  lang="fr"
></agent-shopping>
```

| Attribut | Valeurs | Défaut |
|---|---|---|
| `tenant-id` | string | `default` |
| `api-url` | URL | `https://api.agent-shopping.dev` |
| `primary-color` | hex | `#6C5CE7` |
| `position` | `bottom-right` / `bottom-left` | `bottom-right` |
| `lang` | `fr` / `en` / `ar` | `fr` |

## 6. Fallback

Si notre API est momentanément indisponible, le widget affiche :
```
Service momentanément indisponible. Veuillez réessayer.
```

Vous pouvez configurer un email de contact :
```html
<agent-shopping
  tenant-id="mon-shop"
  ...
  fallback-email="support@monshop.com"
></agent-shopping>
```
