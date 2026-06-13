from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

import requests


class ClientAPIAdapter:
    def __init__(
        self,
        base_url: str = "",
        auth_header: str = "X-API-Key",
        auth_value: str = "",
        timeout: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.auth_value = auth_value
        self.timeout = timeout

        self._endpoint_map: dict[str, str] = {
            "rechercher_produits": "/products/search",
            "details_produit": "/products/{produit_id}",
            "verifier_stock": "/products/{produit_id}/stock",
            "historique_client": "/users/{client_id}/orders",
            "ajouter_panier": "/cart",
            "passer_commande": "/orders",
            "suivre_commande": "/orders/{commande_id}",
        }

        self._mock_catalog: list[dict[str, Any]] = []
        self._load_mock_catalog()

    def _load_mock_catalog(self) -> None:
        try:
            with open("/var/task/mock-catalog.json") as f:
                self._mock_catalog = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._mock_catalog = []

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth_value:
            headers[self.auth_header] = self.auth_value
        return headers

    def _validate_confirmed(self, tool_input: dict[str, Any]) -> None:
        if not tool_input.get("confirmed", False):
            raise ValueError(
                "Confirmation requise. Le client doit confirmer avant d'exécuter cette action."
            )

    def _mock_search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        q = query.lower()
        results = [
            p
            for p in self._mock_catalog
            if q in p.get("nom", "").lower() or q in p.get("description", "").lower()
        ]
        if kwargs.get("categorie"):
            results = [r for r in results if r.get("categorie", "").lower() == kwargs["categorie"].lower()]
        if kwargs.get("min_prix"):
            results = [r for r in results if r.get("prix", 0) >= kwargs["min_prix"]]
        if kwargs.get("max_prix"):
            results = [r for r in results if r.get("prix", 0) <= kwargs["max_prix"]]
        return results[:10]

    def _mock_detail(self, produit_id: str) -> dict[str, Any] | None:
        return next(
            (p for p in self._mock_catalog if p.get("id") == produit_id),
            None,
        )

    def call(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name in ("ajouter_panier", "passer_commande"):
            self._validate_confirmed(tool_input)

        if not self.base_url:
            return self._mock_call(tool_name, tool_input)

        endpoint_template = self._endpoint_map.get(tool_name, "")
        if not endpoint_template:
            return {"error": f"Unknown tool: {tool_name}"}

        endpoint = endpoint_template
        for key, value in tool_input.items():
            placeholder = f"{{{key}}}"
            if placeholder in endpoint:
                endpoint = endpoint.replace(placeholder, str(value))

        url = urljoin(self.base_url, endpoint.lstrip("/"))

        try:
            if tool_name in ("ajouter_panier", "passer_commande"):
                resp = requests.post(url, json=tool_input, headers=self._headers(), timeout=self.timeout)
            else:
                resp = requests.get(url, params=tool_input, headers=self._headers(), timeout=self.timeout)

            resp.raise_for_status()
            return resp.json()

        except requests.Timeout:
            return {"error": "Le service est temporairement indisponible. Veuillez réessayer."}
        except requests.HTTPError as e:
            status = e.response.status_code
            if status == 404:
                return {"error": "Ressource introuvable."}
            if status >= 500:
                return {"error": "Le service est momentanément indisponible."}
            return {"error": f"Erreur de communication ({status})."}

    def _mock_call(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "rechercher_produits":
            return {
                "results": self._mock_search(
                    tool_input.get("query", ""),
                    categorie=tool_input.get("categorie"),
                    min_prix=tool_input.get("min_prix"),
                    max_prix=tool_input.get("max_prix"),
                ),
                "total": len(self._mock_catalog),
            }

        if tool_name == "details_produit":
            product = self._mock_detail(tool_input.get("produit_id", ""))
            return product or {"error": "Produit introuvable."}

        if tool_name == "verifier_stock":
            product = self._mock_detail(tool_input.get("produit_id", ""))
            if not product:
                return {"error": "Produit introuvable."}
            qty = tool_input.get("quantite", 1)
            return {
                "produit_id": product["id"],
                "nom": product["nom"],
                "stock": product.get("stock", 0),
                "disponible": product.get("stock", 0) >= qty,
            }

        if tool_name == "historique_client":
            return {
                "client_id": tool_input.get("client_id", ""),
                "commandes": [],
                "total_commandes": 0,
            }

        if tool_name == "comparer_produits":
            ids = tool_input.get("produits_ids", [])
            products = [self._mock_detail(pid) for pid in ids]
            return {"produits": [p for p in products if p]}

        if tool_name == "ajouter_panier":
            product = self._mock_detail(tool_input.get("produit_id", ""))
            if not product:
                return {"error": "Produit introuvable."}
            return {
                "success": True,
                "message": f"{product['nom']} ajouté au panier.",
                "quantite": tool_input.get("quantite", 1),
            }

        if tool_name == "passer_commande":
            return {
                "success": True,
                "commande_id": "CMD-12345",
                "message": "Commande confirmée !",
            }

        if tool_name == "suivre_commande":
            return {
                "commande_id": tool_input.get("commande_id", ""),
                "statut": "en_cours_de_livraison",
                "date_estimee": "2024-06-20",
            }

        return {"error": f"Tool non implémenté: {tool_name}"}
