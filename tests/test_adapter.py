from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from lambda.adapter import ClientAPIAdapter


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
    # Patch the mock catalog path
    original_path = "/var/task/mock-catalog.json"

    if not os.path.exists("/var/task"):
        os.makedirs("/var/task", exist_ok=True)

    # Use symlink or copy
    if os.path.exists(original_path):
        os.remove(original_path)
    os.symlink(mock_catalog_file, original_path)

    return ClientAPIAdapter(base_url="")


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield
    task_path = Path("/var/task/mock-catalog.json")
    if task_path.exists():
        task_path.unlink()


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

    def test_add_to_cart_without_confirmation_raises(self, adapter: ClientAPIAdapter) -> None:
        with pytest.raises(ValueError, match="Confirmation requise"):
            adapter.call("ajouter_panier", {"produit_id": "PROD-001", "quantite": 1})

    def test_add_to_cart_with_confirmation(self, adapter: ClientAPIAdapter) -> None:
        result = adapter.call(
            "ajouter_panier",
            {"produit_id": "PROD-001", "quantite": 1, "confirmed": True},
        )
        assert result["success"] is True

    def test_place_order_without_confirmation_raises(self, adapter: ClientAPIAdapter) -> None:
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
