# Dette Technique — Agent Shopping

## Priorisation

| # | Dette | Impact | Effort | Priorité |
|---|-------|--------|--------|----------|
| 1 | `rag.py` : 33% de couverture, pas de mock en local | CI manque de confiance | M | **Haute** |
| 2 | `adapter.py` : 68% de couverture, code HTTP jamais testé | Régression silencieuse | M | **Haute** |
| 3 | Module-level `Tracer()` / `Logger()` sans lazy init | Crash silencieux si X-Ray absent en test | S | Haute |
| 4 | Pas de request ID → corrélation logs impossible | Debug en production = devinettes | S | Haute |
| 5 | Dockerfile copie les fichiers un par un | Oubli de module (déjà arrivé avec `tracing.py`) | S | Haute |
| 6 | `Any` partout (handler, adapter, auth) | mypy contourné, refacto risquée | L | Moyenne |
| 7 | `ensure_ascii=False` dupliqué 6× dans handler | Pattern non factorisé | S | Moyenne |
| 8 | `_emit_metric` swallow toutes les exceptions | Une panne CloudWatch masque un vrai problème | M | Moyenne |
| 9 | Pas de validation entrée (pydantic) tout est dict | Erreur 500 sur champ manquant | L | Moyenne |
| 10 | `MAX_TOOL_TURNS=3` sans timeout dynamique | Boucle LLM peut consommer tout le timeout Lambda | M | Moyenne |
| 11 | Pas de cache RAG (même embedding recalculé) | Latence doublée sur questions similaires | M | Basse |
| 12 | Guest tokens auto-signés sans vérification JWKS | Pas une faille (scope limité), mais confusion possible | S | Basse |

---

## 1. `rag.py` — couverture à 33%

**Où** : `lambda/rag.py:16-206`
**Quoi** : 53 lignes non couvertes. Toute la logique OpenSearch (client lazy, embedding, index, search) n'est jamais testée. Le module est contourné par `MOCK_API=true` en local → les tests CI ne l'exercent pas non plus.
**Risque** : Une régression dans la construction de la requête k-NN, le parsing des résultats, ou la gestion d'erreur OpenSearch passerait inaperçue jusqu'au déploiement.
**Fix** : Ajouter des tests avec `opensearch-py` mocké (`@patch("rag._opensearch_client")`), couvrant `search_similar()` et `build_rag_context()`.

## 2. `adapter.py` — branche HTTP jamais testée

**Où** : `lambda/adapter.py:87-120`
**Quoi** : 23 lignes non couvertes. Toute la logique HTTP réelle (`requests.get`, `requests.post`, gestion des timeouts, codes HTTP 404/5xx) n'est jamais exercée. Les tests passent tous par `_mock_call()` via `base_url=""`.
**Risque** : La première vraie intégration HTTP (en staging ou prod) risque de découvrir des bugs de routage, d'en-têtes, ou de gestion d'erreur.
**Fix** : Ajouter des tests HTTP avec `responses` ou `requests_mock`, ou mieux, un conteneur HTTP mock en local.

## 3. `Tracer()` / `Logger()` au module level

**Où** : `lambda/handler.py:16-17`
**Quoi** : `logger = Logger()` et `tracer = Tracer()` sont créés à l'import, pas à l'invocation. `Tracer()` tente de contacter X-Ray au module level.
**Risque** : En test local sans X-Ray daemon, `Tracer()` lève des warnings silencieux. En production, si X-Ray est dégradé, l'import peut ralentir le cold start.
**Fix** : Les rendre lazy via une factory, ou les déplacer dans `lambda_handler()`.

## 4. Pas de request ID

**Où** : Partout dans `lambda/handler.py`
**Quoi** : Aucun identifiant de requête n'est généré ni propagé dans les logs, les métriques CloudWatch, ou les traces LangFuse. Impossible de corréler "cet appel Bedrock" avec "telle requête widget".
**Fix** : Générer un `request_id = str(uuid.uuid4())` dans `lambda_handler()`, l'ajouter aux `extra` de chaque `logger.info()`, au metadata LangFuse, et le retourner dans le header de réponse.

## 5. Dockerfile copie les fichiers individuellement

**Où** : `Dockerfile:18-23`
**Quoi** : Chaque fichier `.py` est copié par une ligne `COPY` explicite. L'ajout de `tracing.py` a nécessité une modification du Dockerfile.
**Risque** : Oubli facile lors de l'ajout d'un module. La Lambda plante au déploiement (ImportError), pas à la compilation.
**Fix** : Remplacer par `COPY lambda/*.py /var/task/` ou utiliser `COPY lambda/ /var/task/` avec un `.dockerignore`.

## 6. `Any` généralisé

**Où** : `lambda/handler.py` (signatures `dict[str, Any]`, `MessageContent`), `lambda/adapter.py`, `lambda/auth.py`
**Quoi** : Les types concrets (`list[dict[str, str]]`, `TypedDict`, `dataclass`) sont absents. `MessageContent = str | list[dict[str, Any]]` est le seul type personnalisé.
**Risque** : mypy ne détecte pas les accès à des clés inexistantes ou des types incorrects. Refactoring dangereux.
**Fix** : Définir des `TypedDict` pour les structures clés (`ToolCall`, `Message`, `Config`, `Response`).

## 7. `ensure_ascii=False` dupliqué

**Où** : `lambda/handler.py:196,210,251,285,590,592`
**Quoi** : 6 appels à `json.dumps(..., ensure_ascii=False)`. Devrait être un helper `_json_dumps()`.
**Risque** : Si le comportement par défaut doit changer (ex: ajouter `default=str` pour les dates), il faut 6 modifications.
**Fix** : Extraire `_json_dumps = functools.partial(json.dumps, ensure_ascii=False)`.

## 8. `_emit_metric` swallow les exceptions

**Où** : `lambda/handler.py:48-49`
**Quoi** : Toute exception CloudWatch est capturée et loggée en warning. Si `_cw_client()` échoue (ex: credentials expirés), aucune alerte n'est levée.
**Risque** : Une panne de monitoring passe inaperçue jusqu'à ce que quelqu'un regarde le dashboard.
**Fix** : Logger en `error` avec stack trace, ajouter une métrique heartbeart, ou ne pas catcher (laisser le Lambda échouer et remonter à CloudWatch Lambda).

## 9. Pas de validation entrée (pydantic)

**Où** : `lambda/handler.py:417-418`
**Quoi** : Le body JSON est parsé avec `json.loads()` et les champs accédés avec `.get()`. Pas de validation de type, pas de schéma.
**Risque** : Une requête mal formée (ex: `message` est un entier) provoque une erreur 500 au lieu d'une 400.
**Fix** : Ajouter un modèle pydantic `ChatRequest` et `validate_call`.

## 10. `MAX_TOOL_TURNS=3` sans timeout dynamique

**Où** : `lambda/handler.py:20`
**Quoi** : Le nombre de tours d'outils est fixe (3). Si chaque tour prend 8s, le Lambda timeout à 30s et le client reçoit une erreur 503 sans explication.
**Risque** : UX dégradée sur les conversations complexes sans fallback élégant.
**Fix** : Calculer le temps restant (`context.get_remaining_time_in_millis()`) avant chaque tour et sortir avec un message explicite si le timeout approche.

## 11. Pas de cache RAG

**Où** : `lambda/rag.py`
**Quoi** : À chaque requête non-fast-path, un nouvel embedding Titan est calculé et une recherche OpenSearch est effectuée. Aucun cache pour les questions fréquentes ou les embeddings.
**Risque** : Latence doublée (embedding + search + LLM). Coût plus élevé (Titan embedding facturé à l'appel).
**Fix** : Cache LRU en mémoire (`functools.lru_cache` sur l'embedding, ou cache Redis si distribué).

## 12. Guest tokens auto-signés

**Où** : `lambda/auth.py`
**Quoi** : Les tokens guest sont générés côté Lambda (auto-signés via `cryptography`). Pas de vérification JWKS pour ces tokens.
**Risque** : Pas une faille (scope limité : pas d'accès API client, pas de transaction). Mais la confusion entre "authentifié via JWT client" et "guest auto-signé" peut mener à des erreurs d'intégration.
**Fix** : Ajouter un champ `token_type: "guest" | "authenticated"` explicite dans le token.
