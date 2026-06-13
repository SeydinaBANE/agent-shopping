from __future__ import annotations

import json
import tempfile
from unittest.mock import patch

import pytest
import requests

from adapter import ClientAPIAdapter


@pytest.fixture
def mock_catalog_file() -> str:
    catalog = [
        {
            "id": "PROD-001",
            "nom": "Test Product",
            "description": "A test product",
            "prix": 29.99,
            "stock": 10,
            "categorie": "test",
            "tags": ["test"],
        },
        {
            "id": "PROD-002",
            "nom": "Another Product",
            "description": "Another test product",
            "prix": 49.99,
            "stock": 5,
            "categorie": "test",
            "tags": ["test"],
        },
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(catalog, f)
        return f.name


@pytest.fixture
def adapter(mock_catalog_file: str) -> ClientAPIAdapter:
    return ClientAPIAdapter(base_url="", catalog_path=mock_catalog_file)


class TestClientAPIAdapter:
    def test_search_products(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call("rechercher_produits", {"query": "test"})
        assert "results" in result
        assert len(result["results"]) == 2

    def test_search_products_filter_by_price(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call(
            "rechercher_produits",
            {"query": "test", "min_prix": 30.0},
        )
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "PROD-002"

    def test_product_detail_found(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call("details_produit", {"produit_id": "PROD-001"})
        assert result is not None
        assert result["nom"] == "Test Product"
        assert result["prix"] == 29.99

    def test_product_detail_not_found(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call("details_produit", {"produit_id": "PROD-999"})
        assert result == {"error": "Produit introuvable."}

    def test_check_stock_available(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call("verifier_stock", {"produit_id": "PROD-001"})
        assert result["disponible"] is True
        assert result["stock"] == 10

    def test_check_stock_insufficient(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call(
            "verifier_stock",
            {"produit_id": "PROD-002", "quantite": 10},
        )
        assert result["disponible"] is False
        assert result["stock"] == 5

    def test_add_to_cart_without_confirmation_raises(
        self, adapter: ClientAPIAdapter
    ) -> None:
        with pytest.raises(ValueError, match="Confirmation requise"):
            adapter.call("ajouter_panier", {"produit_id": "PROD-001", "quantite": 1})

    def test_add_to_cart_with_confirmation(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call(
            "ajouter_panier",
            {"produit_id": "PROD-001", "quantite": 1, "confirmed": True},
        )
        assert result["success"] is True

    def test_place_order_without_confirmation_raises(
        self, adapter: ClientAPIAdapter
    ) -> None:
        with pytest.raises(ValueError, match="Confirmation requise"):
            adapter.call("passer_commande", {})

    def test_place_order_with_confirmation(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call(
            "passer_commande",
            {"confirmed": True},
        )
        assert result["success"] is True
        assert "commande_id" in result

    def test_track_order(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call(
            "suivre_commande",
            {"commande_id": "CMD-123"},
        )
        assert result["statut"] == "en_cours_de_livraison"
        assert "date_estimee" in result

    def test_compare_products(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call(
            "comparer_produits",
            {"produits_ids": ["PROD-001", "PROD-002"]},
        )
        assert len(result["produits"]) == 2

    def test_user_history(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call(
            "historique_client",
            {"client_id": "user-123"},
        )
        assert result["client_id"] == "user-123"
        assert result["total_commandes"] == 0

    def test_empty_query(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call("rechercher_produits", {"query": ""})
        assert len(result["results"]) == 0

    def test_unknown_tool(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call("unknown_tool", {})
        assert "error" in result

    def test_http_base_url_rejected(self, adapter: ClientAPIAdapter) -> None:
        adapter.base_url = "http://internal.service:8080"
        with patch.object(adapter, "_mock_call") as mock_mock:
            result = adapter.call("rechercher_produits", {"query": "test"})
            assert "error" in result
            assert "HTTPS" in result["error"]
            mock_mock.assert_not_called()

    def test_https_base_url_allowed(self, adapter: ClientAPIAdapter) -> None:
        adapter.base_url = "https://api.example.com"
        with patch("adapter.requests.get") as mock_get:
            mock_get.return_value.ok = True
            mock_get.return_value.json.return_value = {"results": []}
            result = adapter.call("rechercher_produits", {"query": "test"})
            assert "results" in result

    def test_http_timeout_returns_friendly_error(
        self, adapter: ClientAPIAdapter
    ) -> None:
        adapter.base_url = "https://api.example.com"
        with patch("adapter.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout("timed out")
            result = adapter.call("rechercher_produits", {"query": "test"})
            assert "temporairement indisponible" in result["error"]

    def test_http_404_returns_not_found(self, adapter: ClientAPIAdapter) -> None:
        adapter.base_url = "https://api.example.com"
        with patch("adapter.requests.get") as mock_get:
            resp = _error_response(404)
            mock_get.return_value = resp
            result = adapter.call("rechercher_produits", {"query": "test"})
            assert "Ressource introuvable" in result["error"]

    def test_http_500_returns_service_unavailable(
        self, adapter: ClientAPIAdapter
    ) -> None:
        adapter.base_url = "https://api.example.com"
        with patch("adapter.requests.get") as mock_get:
            resp = _error_response(502)
            mock_get.return_value = resp
            result = adapter.call("rechercher_produits", {"query": "test"})
            assert "momentanément indisponible" in result["error"]

    def test_http_403_returns_generic_error(self, adapter: ClientAPIAdapter) -> None:
        adapter.base_url = "https://api.example.com"
        with patch("adapter.requests.get") as mock_get:
            resp = _error_response(403)
            mock_get.return_value = resp
            result = adapter.call("rechercher_produits", {"query": "test"})
            assert "403" in result["error"]

    def test_post_cart_via_https(self, adapter: ClientAPIAdapter) -> None:
        adapter.base_url = "https://api.example.com"
        with patch("adapter.requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = {"success": True}
            result = adapter.call(
                "ajouter_panier",
                {"produit_id": "PROD-001", "quantite": 1, "confirmed": True},
            )
            assert result["success"] is True
            mock_post.assert_called_once()

    def test_post_cart_timeout(self, adapter: ClientAPIAdapter) -> None:
        adapter.base_url = "https://api.example.com"
        with patch("adapter.requests.post") as mock_post:
            mock_post.side_effect = requests.Timeout("timeout")
            result = adapter.call(
                "ajouter_panier",
                {"produit_id": "PROD-001", "quantite": 1, "confirmed": True},
            )
            assert "temporairement indisponible" in result["error"]


def _error_response(status: int) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    return resp
