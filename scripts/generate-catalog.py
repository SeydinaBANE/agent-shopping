"""Generate a synthetic product catalog using Bedrock."""

from __future__ import annotations

import json
import os
import random

import boto3

CATEGORIES = ["vêtements", "électronique", "maison", "alimentation", "sport", "beauté"]
PRODUCT_COUNT = 500

PROMPT = f"""Génère un catalogue de {PRODUCT_COUNT} produits e-commerce au format JSON.
Chaque produit a les champs : id, nom, description, prix, stock, catégorie, tags.
Les catégories possibles : {', '.join(CATEGORIES)}.
Les prix doivent être réalistes. Les descriptions en français, 1-2 phrases.
Format : un tableau JSON valide uniquement, rien d'autre.

Exemple :
{{"id": "PROD-001", "nom": "Robe d'été fleurie", "description": "Robe légère en coton bio, parfaite pour les journées ensoleillées.", "prix": 49.99, "stock": 42, "categorie": "vêtements", "tags": ["robe", "été", "fleurie", "coton"]}}"""


def generate_catalog() -> list[dict]:
    bedrock = boto3.client("bedrock-runtime")

    response = bedrock.invoke_model(
        modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": PROMPT}],
        }),
    )

    body = json.loads(response["body"].read())
    content = body["content"][0]["text"]

    # Extract JSON array from response
    start = content.find("[")
    end = content.rfind("]") + 1
    return json.loads(content[start:end])


def main() -> None:
    output_path = os.environ.get(
        "OUTPUT_PATH",
        os.path.join(os.path.dirname(__file__), "..", "api", "mock-catalog.json"),
    )

    print(f"Generating {PRODUCT_COUNT} products...")
    try:
        catalog = generate_catalog()
    except Exception as e:
        print(f"Bedrock generation failed: {e}")
        print("Falling back to deterministic catalog...")
        catalog = _generate_fallback()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"Catalog saved to {output_path}")
    print(f"Total products: {len(catalog)}")


def _generate_fallback() -> list[dict]:
    catalog = []
    adjectives = ["Élégant", "Moderne", "Classique", "Premium", "Confortable", "Léger"]
    nouns = ["Pull", "Téléphone", "Lampe", "Chaise", "Sac", "Montre", "Livre", "Casque"]

    for i in range(PRODUCT_COUNT):
        adj = random.choice(adjectives)
        noun = random.choice(nouns)
        category = random.choice(CATEGORIES)
        price = round(random.uniform(9.99, 299.99), 2)

        catalog.append({
            "id": f"PROD-{i+1:04d}",
            "nom": f"{adj} {noun}",
            "description": f"{adj} {noun.lower()} de qualité supérieure. Parfait pour votre quotidien.",
            "prix": price,
            "stock": random.randint(0, 150),
            "categorie": category,
            "tags": [noun.lower(), adj.lower(), category],
        })

    return catalog


if __name__ == "__main__":
    main()
