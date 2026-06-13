from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))

from rag import bulk_index_products, ensure_index


CATALOG_PATH = os.environ.get(
    "CATALOG_PATH",
    os.path.join(os.path.dirname(__file__), "..", "api", "mock-catalog.json"),
)


def load_catalog(path: str) -> list[dict[str, Any]]:
    with open(path) as f:
        return json.load(f)


def main() -> None:
    tenant_id = os.environ.get("TENANT_ID", "default")
    catalog = load_catalog(CATALOG_PATH)

    print(f"Chargement de {len(catalog)} produits depuis {CATALOG_PATH}")
    print(f"Tenant: {tenant_id}")

    if not ensure_index(tenant_id):
        print("❌ Index OpenSearch non créé (mode mock ou hors ligne)")
        print("   Lance docker compose up d'abord.")
        sys.exit(1)

    print("✅ Index prêt, indexation en cours...")
    count = bulk_index_products(tenant_id, catalog)
    print(f"✅ {count} produits indexés dans OpenSearch")


if __name__ == "__main__":
    main()
