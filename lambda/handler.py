from __future__ import annotations

import json
import os
from typing import Any

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from adapter import ClientAPIAdapter
from rag import build_rag_context, search_similar

logger = Logger()
tracer = Tracer()

bedrock_runtime = boto3.client("bedrock-runtime")
ssm = boto3.client("ssm")

MODEL_SONNET = os.environ.get(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
)
MODEL_HAIKU = os.environ.get(
    "BEDROCK_FAST_MODEL_ID",
    "anthropic.claude-3-haiku-20240307-v1:0",
)


FAST_PATTERNS = [
    "bonjour",
    "salut",
    "merci",
    "au revoir",
    "bonne journée",
    "oui",
    "non",
]


def _is_fast_path(message: str) -> bool:
    msg = message.strip().lower()
    return any(pattern == msg for pattern in FAST_PATTERNS)


def _get_tenant_config(tenant_id: str) -> dict[str, Any]:
    path = f"/agent-shopping/tenants/{tenant_id}"
    try:
        params = ssm.get_parameters_by_path(Path=path, Recursive=True, WithDecryption=True)
        config: dict[str, Any] = {}
        for param in params.get("Parameters", []):
            key = param["Name"].split("/")[-1]
            config[key] = param["Value"]
        return config
    except ssm.exceptions.ParameterNotFound:
        logger.warning("tenant_config_not_found", tenant_id=tenant_id)
        return {}


def _invoke_bedrock(
    messages: list[dict[str, str]],
    system_prompt: str,
    tools: list[dict[str, Any]],
    fast: bool = False,
) -> dict[str, Any]:
    model_id = MODEL_HAIKU if fast else MODEL_SONNET

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": int(os.environ.get("BEDROCK_MAX_TOKENS", "1024")),
        "temperature": float(os.environ.get("BEDROCK_TEMPERATURE", "0.3")),
        "system": system_prompt,
        "messages": messages,
        "tools": tools,
    }

    response = bedrock_runtime.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )

    return json.loads(response["body"].read())


def _build_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "rechercher_produits",
            "description": "Rechercher des produits dans le catalogue",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "La recherche du client"},
                    "categorie": {"type": "string", "description": "Catégorie optionnelle"},
                    "min_prix": {"type": "number", "description": "Prix minimum"},
                    "max_prix": {"type": "number", "description": "Prix maximum"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "details_produit",
            "description": "Obtenir les détails complets d'un produit",
            "input_schema": {
                "type": "object",
                "properties": {
                    "produit_id": {"type": "string", "description": "ID du produit"},
                },
                "required": ["produit_id"],
            },
        },
        {
            "name": "verifier_stock",
            "description": "Vérifier le stock disponible d'un produit",
            "input_schema": {
                "type": "object",
                "properties": {
                    "produit_id": {"type": "string", "description": "ID du produit"},
                    "quantite": {"type": "integer", "description": "Quantité souhaitée"},
                },
                "required": ["produit_id"],
            },
        },
        {
            "name": "historique_client",
            "description": "Obtenir l'historique des commandes d'un client",
            "input_schema": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "string", "description": "ID du client"},
                },
                "required": ["client_id"],
            },
        },
        {
            "name": "comparer_produits",
            "description": "Comparer plusieurs produits côte à côte",
            "input_schema": {
                "type": "object",
                "properties": {
                    "produits_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste des IDs de produits à comparer",
                    },
                },
                "required": ["produits_ids"],
            },
        },
        {
            "name": "ajouter_panier",
            "description": "Ajouter un produit au panier du client",
            "input_schema": {
                "type": "object",
                "properties": {
                    "produit_id": {"type": "string", "description": "ID du produit"},
                    "quantite": {"type": "integer", "description": "Quantité"},
                    "confirmed": {
                        "type": "boolean",
                        "description": "Confirmation obligatoire pour exécuter",
                    },
                },
                "required": ["produit_id", "quantite", "confirmed"],
            },
        },
        {
            "name": "passer_commande",
            "description": "Passer la commande finale",
            "input_schema": {
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "boolean",
                        "description": "Confirmation obligatoire pour exécuter",
                    },
                },
                "required": ["confirmed"],
            },
        },
        {
            "name": "suivre_commande",
            "description": "Suivre l'état d'une commande",
            "input_schema": {
                "type": "object",
                "properties": {
                    "commande_id": {"type": "string", "description": "ID de la commande"},
                },
                "required": ["commande_id"],
            },
        },
    ]


SYSTEM_PROMPT = """Tu es un assistant shopping en français. Tu aides les clients à trouver des
produits et à passer commande sur leur site e-commerce.

Règles :
- Sois concis, amical et professionnel
- Réponds toujours en français
- Si un produit n'existe pas, dis-le franchement
- Propose des alternatives quand un produit n'est pas disponible
- Ne JAMAIS inventer de produits ou de prix
- Pour toute action de panier ou commande, tu dois d'abord demander la confirmation au client
- Le paramètre "confirmed" doit être false tant que le client n'a pas explicitement confirmé
- Si le client demande une action non liée au shopping, explique poliment que tu ne peux pas aider

Format des réponses produits :
"**Nom du produit** — XX,XX€ | Stock : X unités"

Pour les comparaisons, utilise un tableau simple."""


@tracer.capture_lambda_handler
@logger.inject_lambda_context
def lambda_handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"})}

    message = body.get("message", "")
    history = body.get("history", [])
    tenant_id = body.get("tenant_id", "default")

    if not message:
        return {"statusCode": 400, "body": json.dumps({"error": "Message is required"})}

    config = _get_tenant_config(tenant_id)

    adapter = ClientAPIAdapter(
        base_url=config.get("api_base_url", ""),
        auth_header=config.get("api_auth_header", "X-API-Key"),
        auth_value=config.get("api_auth_value", ""),
    )

    fast = _is_fast_path(message)
    messages = history + [{"role": "user", "content": message}]
    tools = _build_tools()

    rag_context = ""
    if not fast:
        results = search_similar(message, tenant_id)
        if results:
            rag_context = build_rag_context(results)

    system_prompt = f"{rag_context}\n\n{SYSTEM_PROMPT}" if rag_context else SYSTEM_PROMPT

    response = _invoke_bedrock(
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
        fast=fast,
    )

    result = _handle_bedrock_response(response, adapter)

    logger.info(
        "conversation_processed",
        extra={
            "tenant_id": tenant_id,
            "fast_path": fast,
            "latency_ms": int(context.get_remaining_time_in_millis() or 0),
            "tool_calls": result.get("tool_calls_count", 0),
        },
    )

    return {"statusCode": 200, "body": json.dumps(result)}


def _handle_bedrock_response(
    response: dict[str, Any],
    adapter: ClientAPIAdapter,
) -> dict[str, Any]:
    content = response.get("content", [])
    output_text = ""
    tool_calls_count = 0

    for block in content:
        if block.get("type") == "text":
            output_text += block["text"]

        elif block.get("type") == "tool_use":
            tool_calls_count += 1
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})

            tool_result = adapter.call(tool_name, tool_input)
            # In a real implementation, we would feed this back to Bedrock
            # For POC, we append it to the output
            output_text += f"\n[{tool_name}] {json.dumps(tool_result, ensure_ascii=False)}"

    return {
        "response": output_text,
        "tool_calls_count": tool_calls_count,
    }
