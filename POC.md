# POC — Agent Shopping Conversationnel
**Durée : 2 semaines**
**Objectif :** Prouver qu'un agent Bedrock peut comprendre une requête en français, chercher un produit dans un catalogue, et répondre — le tout depuis un Web Component.

## Semaine 1 — Backend
### J1-2 : Données synthétiques
- Script `generate-catalog.py` : prompt Bedrock → 500 produits (vêtements, électronique, maison)
- Output : `catalog.json` avec `{id, nom, description, prix, stock, catégorie, tags}`
- Script `generate-qa.py` : 50 paires question/réponse pour test manuel

### J3-4 : API mock + Lambda orchestrateur
- Lambda Python :
  - Endpoint POST `/assistant/chat`
  - Reçoit `{message, history[], tenant_id}`
  - Valide une API key simple (pas de JWT encore)
  - Renvoie `{response, tools_called[]}`
- API mock intégrée à la Lambda (JSON statique en mémoire)

### J5 : Connexion Bedrock
- Création Bedrock KB sur les 500 produits (Titan Embeddings → OpenSearch)
- Prompt système en français :
  ```
  Tu es un assistant shopping en français. Tu aides les clients à trouver des produits.
  Sois concis et amical. Si un produit n'existe pas, dis-le franchement.
  Format : "produit | prix | stock"
  ```
- 3 outils :
  - `rechercher_produits(query, categorie?, min_prix?, max_prix?)`
  - `details_produit(produit_id)`
  - `verifier_stock(produit_id, quantite?)`

## Semaine 2 — Frontend + Intégration
### J6-7 : Web Component `<agent-shopping>` v0
- Fichier unique `agent-shopping.js`
- Shadow DOM, pas de dépendances
- Bouton flottant → popup de chat
- Input text + bouton envoyer
- API call vers Lambda, affichage de la réponse

### J8-9 : Streaming différé + intégration
- Call REST (pas WebSocket encore)
- Affichage progressif simulé (charactère par charactère côté JS)
- Test sur 3 sites factices (React, HTML statique, Shopify placeholders)

### J10 : Buffer + Démo
- Correction bugs
- Démo de 3 scénarios :
  1. "Je cherche une robe rouge pour un mariage" → retourne 3 résultats
  2. "Donne-moi les détails du 2e" → fiche produit
  3. "Il est en stock ?" → oui/non + quantité

## Livrables POC
- `scripts/generate-catalog.py`
- `scripts/generate-qa.py`
- `api/mock-catalog.json`
- `lambda/handler.py`
- `widget/agent-shopping.js`
- `docker-compose.yml` (Lambda locale via SAM CLI)

## Tests de validation POC
- [ ] 3 scénarios de bout en bout fonctionnent
- [ ] Latence < 5s par message
- [ ] Widget s'intègre dans une page React et une page HTML statique
- [ ] Réponses en français correct
- [ ] Prompt injection basique bloqué (ex: "ignore les instructions précédentes")
