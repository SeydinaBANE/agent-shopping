"""Generate synthetic QA pairs for testing the shopping assistant."""

from __future__ import annotations

import json
import os
import random

QUESTIONS = [
    "Bonjour",
    "Je cherche une robe rouge",
    "Quel est le prix du pull noir ?",
    "Vous avez des écouteurs sans fil ?",
    "Je veux un cadeau pour ma femme, max 50€",
    "Comparez les deux robes que vous m'avez montrées",
    "Ajoute la robe rouge à mon panier",
    "Je passe commande",
    "Quel est le statut de ma commande CMD-123 ?",
    "Merci beaucoup !",
    "Montre-moi les chaussures de sport",
    "Il me faut une lampe pour le bureau",
    "Est-ce que le sac est en stock ?",
    "Je veux annuler ma commande",
    "Quels sont vos produits les moins chers ?",
]

RANDOM_QUESTIONS = [
    "Tu peux me trouver un manteau d'hiver ?",
    "J'ai besoin d'une nouvelle batterie externe",
    "Qu'est-ce que vous avez en promotion ?",
    "Donne-moi le détail du produit PROD-042",
    "Ajoute le casque audio à mon panier",
    "Combien coûte la montre connectée ?",
    "Y a-t-il une garantie sur les appareils électroniques ?",
    "Je cherche un cadeau original",
    "Est-ce que vous livrez en Suisse ?",
    "Peux-tu me recommander un bon roman ?",
]


def generate_qa_pairs(count: int = 50) -> list[dict]:
    all_questions = QUESTIONS + RANDOM_QUESTIONS
    qa_pairs = []

    for i in range(min(count, len(all_questions))):
        qa_pairs.append({
            "id": f"QA-{i+1:03d}",
            "question": all_questions[i],
            "expected_tools": _expected_tools(all_questions[i]),
        })

    # Add remaining random QAs
    for i in range(count - len(all_questions)):
        q = random.choice(RANDOM_QUESTIONS)
        qa_pairs.append({
            "id": f"QA-{len(all_questions)+i+1:03d}",
            "question": q,
            "expected_tools": _expected_tools(q),
        })

    return qa_pairs


def _expected_tools(question: str) -> list[str]:
    q = question.lower()

    if any(word in q for word in ["cherche", "trouver", "montre", "besoin", "avoir"]):
        return ["rechercher_produits"]
    if "prix" in q or "coûte" in q or "combien" in q:
        return ["details_produit"]
    if "stock" in q or "disponible" in q:
        return ["verifier_stock"]
    if "compare" in q:
        return ["comparer_produits"]
    if "ajoute" in q or "panier" in q:
        return ["ajouter_panier"]
    if "commande" in q or "cmd-" in q:
        return ["passer_commande", "suivre_commande"]
    if "statut" in q:
        return ["suivre_commande"]
    if any(word in q for word in ["bonjour", "salut", "merci"]):
        return []

    return ["rechercher_produits"]


def main() -> None:
    output_path = os.environ.get(
        "OUTPUT_PATH",
        os.path.join(os.path.dirname(__file__), "..", "api", "qa-pairs.json"),
    )

    qa_pairs = generate_qa_pairs(50)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(qa_pairs, f, ensure_ascii=False, indent=2)

    print(f"Generated {len(qa_pairs)} QA pairs → {output_path}")


if __name__ == "__main__":
    main()
