from __future__ import annotations

import functools
import json
import os
import uuid
from typing import Any, TypedDict

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from adapter import ClientAPIAdapter
from auth import extract_user_context
from rag import build_rag_context, search_similar
from tracing import create_trace, flush

logger = Logger()

METRICS_NAMESPACE = "AgentShopping"
MAX_TOOL_TURNS = 3
MessageContent = str | list[dict[str, Any]]

_json = functools.partial(json.dumps, ensure_ascii=False)


class ToolUse(TypedDict):
    type: str
    name: str
    id: str
    input: dict[str, Any]


class ToolResult(TypedDict):
    type: str
    tool_use_id: str
    content: str


class ConversationResult(TypedDict):
    response: str
    tool_calls_count: int


def _bedrock_client():
    return boto3.client("bedrock-runtime")


def _ssm_client():
    return boto3.client("ssm")


def _cw_client():
    return boto3.client("cloudwatch")


def _emit_metric(name: str, value: float, unit: str, dimensions: list[dict[str, str]]) -> None:
    try:
        _cw_client().put_metric_data(
            Namespace=METRICS_NAMESPACE,
            MetricData=[
                {
                    "MetricName": name,
                    "Value": value,
                    "Unit": unit,
                    "Dimensions": dimensions,
                }
            ],
        )
    except Exception:
        logger.exception("metric_emit_failed", metric_name=name)


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
    client = _ssm_client()
    path = f"/agent-shopping/tenants/{tenant_id}"
    try:
        params = client.get_parameters_by_path(Path=path, Recursive=True, WithDecryption=True)
        for param in params.get("Parameters", []):
            key = param["Name"].split("/")[-1]
            if key == "config":
                return json.loads(param["Value"])
        return {}
    except client.exceptions.ParameterNotFound:
        logger.warning("tenant_config_not_found", tenant_id=tenant_id)
        return {}


def _write_sse(response_stream, data: str) -> None:
    response_stream.write(f"data: {data}\n\n".encode())


def _invoke_bedrock(
    messages: list[dict[str, MessageContent]],
    system_prompt: str,
    tools: list[dict[str, Any]],
    fast: bool = False,
    lf_generation: Any = None,
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

    response = _bedrock_client().invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=_json(body),
    )

    result = json.loads(response["body"].read())

    usage = result.get("usage", {})
    dims = [{"Name": "Model", "Value": model_id}]
    _emit_metric("Invocation", 1, "Count", dims)
    token_count = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    if token_count:
        _emit_metric("Tokens", token_count, "Count", dims)

    if lf_generation is not None:
        lf_generation.end(
            output=result,
            usage={
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "unit": "TOKENS",
            },
        )

    return result


def _invoke_bedrock_stream(
    messages: list[dict[str, MessageContent]],
    system_prompt: str,
    tools: list[dict[str, Any]],
    adapter: ClientAPIAdapter,
    response_stream,
    fast: bool = False,
    lf_trace: Any = None,
    context: LambdaContext | None = None,
) -> int:
    model_id = MODEL_HAIKU if fast else MODEL_SONNET

    stream_gen = (
        lf_trace.generation(
            name="bedrock-stream",
            model=model_id,
            input={"messages": messages, "system": system_prompt, "tools": tools},
            metadata={"fast": fast},
        )
        if lf_trace is not None
        else None
    )

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": int(os.environ.get("BEDROCK_MAX_TOKENS", "1024")),
        "temperature": float(os.environ.get("BEDROCK_TEMPERATURE", "0.3")),
        "system": system_prompt,
        "messages": messages,
        "tools": tools,
    }

    streaming_response = _bedrock_client().invoke_model_with_response_stream(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=_json(request_body),
    )

    total_tool_calls = 0
    content_blocks: list[dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for event in streaming_response["body"]:
        chunk = json.loads(event["chunk"]["bytes"])
        chunk_type = chunk.get("type")

        if chunk_type == "content_block_start":
            block = chunk.get("content_block", {})
            if block.get("type") == "tool_use":
                payload = _json({"type": "tool_start", "name": block["name"]})
                _write_sse(response_stream, payload)
            content_blocks.append(block)

        elif chunk_type == "content_block_delta":
            delta = chunk.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if content_blocks:
                    last = content_blocks[-1]
                    last["text"] = last.get("text", "") + text
                _write_sse(
                    response_stream,
                    _json({"type": "text", "text": text}),
                )

        elif chunk_type == "message_delta":
            usage = chunk.get("usage", {})
            total_input_tokens = usage.get("input_tokens", 0)
            total_output_tokens = usage.get("output_tokens", 0)

    tool_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
    if tool_blocks:
        tool_results, count = _process_tool_calls(content_blocks, adapter)
        total_tool_calls = count

        messages = [
            *messages,
            {"role": "assistant", "content": content_blocks},
            {"role": "user", "content": tool_results},
        ]

        for turn_i in range(MAX_TOOL_TURNS):
            if context and context.get_remaining_time_in_millis() < 3000:
                break

            sync_gen = (
                lf_trace.generation(
                    name="bedrock-invoke",
                    model=MODEL_SONNET,
                    input={"messages": messages, "system": system_prompt},
                    metadata={"turn": turn_i, "fast": False, "stream_follow_up": True},
                )
                if lf_trace is not None
                else None
            )

            response = _invoke_bedrock(
                messages,
                system_prompt,
                tools,
                fast=False,
                lf_generation=sync_gen,
            )
            next_content = response.get("content", [])
            next_text = "".join(b.get("text", "") for b in next_content if b.get("type") == "text")
            if next_text:
                payload = _json({"type": "text", "text": next_text})
                _write_sse(response_stream, payload)

            next_tool_blocks = [b for b in next_content if b.get("type") == "tool_use"]
            if not next_tool_blocks:
                break

            tool_results2, count2 = _process_tool_calls(next_content, adapter)
            total_tool_calls += count2
            messages = [
                *messages,
                {"role": "assistant", "content": next_content},
                {"role": "user", "content": tool_results2},
            ]

    dims = [{"Name": "Model", "Value": model_id}]
    _emit_metric("Invocation", 1, "Count", dims)
    token_count = total_input_tokens + total_output_tokens
    if token_count:
        _emit_metric("Tokens", token_count, "Count", dims)

    if stream_gen is not None:
        text_blocks = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        stream_gen.end(
            output={"content": content_blocks, "text": "".join(text_blocks)},
            usage={
                "input": total_input_tokens,
                "output": total_output_tokens,
                "unit": "TOKENS",
            },
        )

    _write_sse(
        response_stream,
        _json({"type": "done", "tool_calls": total_tool_calls}),
    )
    return total_tool_calls


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


@logger.inject_lambda_context
def lambda_handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any] | None:
    start_remaining = context.get_remaining_time_in_millis()
    request_id = str(uuid.uuid4())

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": _json({"error": "Invalid JSON"})}

    message = body.get("message", "")
    history = body.get("history", [])
    tenant_id = body.get("tenant_id", "default")

    if not message:
        return {"statusCode": 400, "body": _json({"error": "Message is required"})}

    if len(message) > 2000:
        return {
            "statusCode": 400,
            "body": _json({"error": "Message trop long (max 2000 caractères)"}),
        }

    headers = event.get("headers", {}) or {}
    auth_header = headers.get("authorization", headers.get("Authorization", ""))
    token = auth_header.removeprefix("Bearer ").strip() if auth_header else None

    config = _get_tenant_config(tenant_id)
    jwks_uri = config.get("public_key_jwks_uri", "")

    user_ctx = extract_user_context(token, jwks_uri)
    is_auth = user_ctx.get("user_context", {}).get("mode") == "authenticated"
    if is_auth and user_ctx.get("tenant_id") != tenant_id:
        return {"statusCode": 403, "body": _json({"error": "Tenant mismatch"})}

    if not is_auth:
        user_ctx["tenant_id"] = "guest"
        tenant_id = "guest"
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

    lf_trace = create_trace(
        name="agent-shopping",
        user_id=user_ctx.get("sub"),
        session_id=tenant_id,
        metadata={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "user_mode": user_ctx.get("user_context", {}).get("mode", "unknown"),
            "fast_path": fast,
            "has_rag": bool(rag_context),
        },
    )

    response_stream = getattr(context, "response_stream", None)

    try:
        if response_stream:
            _run_conversation_streaming(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                adapter=adapter,
                response_stream=response_stream,
                fast=fast,
                tenant_id=tenant_id,
                user_ctx=user_ctx,
                context=context,
                start_remaining=start_remaining,
                lf_trace=lf_trace,
                request_id=request_id,
            )
            return None

        result = _run_conversation(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            adapter=adapter,
            fast=fast,
            lf_trace=lf_trace,
            context=context,
        )

        elapsed_ms = start_remaining - context.get_remaining_time_in_millis()
        dims = [{"Name": "Model", "Value": MODEL_HAIKU if fast else MODEL_SONNET}]
        _emit_metric("Latency", elapsed_ms, "Milliseconds", dims)

        logger.info(
            "conversation_processed",
            extra={
                "request_id": request_id,
                "tenant_id": tenant_id,
                "user_sub": user_ctx.get("sub", "unknown"),
                "user_mode": user_ctx.get("user_context", {}).get("mode", "unknown"),
                "fast_path": fast,
                "latency_ms": elapsed_ms,
                "tool_calls": result.get("tool_calls_count", 0),
            },
        )

        return {
            "statusCode": 200,
            "headers": {"X-Request-Id": request_id},
            "body": _json(result),
        }
    finally:
        flush()


def _run_conversation_streaming(
    messages: list[dict[str, MessageContent]],
    system_prompt: str,
    tools: list[dict[str, Any]],
    adapter: ClientAPIAdapter,
    response_stream,
    fast: bool,
    tenant_id: str,
    user_ctx: dict[str, Any],
    context: LambdaContext,
    start_remaining: int,
    lf_trace: Any = None,
    request_id: str = "",
) -> None:
    total_tool_calls = _invoke_bedrock_stream(
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
        adapter=adapter,
        response_stream=response_stream,
        fast=fast,
        lf_trace=lf_trace,
        context=context,
    )

    elapsed_ms = start_remaining - context.get_remaining_time_in_millis()
    dims = [{"Name": "Model", "Value": MODEL_HAIKU if fast else MODEL_SONNET}]
    _emit_metric("Latency", elapsed_ms, "Milliseconds", dims)

    logger.info(
        "conversation_streamed",
        extra={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "user_sub": user_ctx.get("sub", "unknown"),
            "user_mode": user_ctx.get("user_context", {}).get("mode", "unknown"),
            "fast_path": fast,
            "latency_ms": elapsed_ms,
            "tool_calls": total_tool_calls,
        },
    )


def _process_tool_calls(
    content: list[dict[str, Any]],
    adapter: ClientAPIAdapter,
) -> tuple[list[dict[str, Any]], int]:
    blocks: list[dict[str, Any]] = []
    count = 0

    for block in content:
        if block.get("type") != "tool_use":
            continue

        count += 1
        tool_name = block.get("name", "")
        tool_input = block.get("input", {})
        tool_use_id = block.get("id", "")

        try:
            result = adapter.call(tool_name, tool_input)
            result_str = _json(result)
        except Exception as e:
            result_str = _json({"error": str(e)})

        blocks.append(
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result_str,
            }
        )

    return blocks, count


def _run_conversation(
    messages: list[dict[str, MessageContent]],
    system_prompt: str,
    tools: list[dict[str, Any]],
    adapter: ClientAPIAdapter,
    fast: bool = False,
    lf_trace: Any = None,
    context: LambdaContext | None = None,
) -> ConversationResult:
    content: list[dict[str, Any]] = []
    total_tool_calls = 0

    for i in range(MAX_TOOL_TURNS):
        if context and context.get_remaining_time_in_millis() < 3000:
            break

        use_fast = fast and i == 0
        model_id = MODEL_HAIKU if use_fast else MODEL_SONNET
        gen = (
            lf_trace.generation(
                name="bedrock-invoke",
                model=model_id,
                input={"messages": messages, "system": system_prompt},
                metadata={"turn": i, "fast": use_fast},
            )
            if lf_trace is not None
            else None
        )

        response = _invoke_bedrock(
            messages,
            system_prompt,
            tools,
            fast=use_fast,
            lf_generation=gen,
        )
        content = response.get("content", [])

        tool_blocks = [b for b in content if b.get("type") == "tool_use"]
        if not tool_blocks:
            break

        tool_results, count = _process_tool_calls(content, adapter)
        total_tool_calls += count

        messages = [
            *messages,
            {"role": "assistant", "content": content},
            {"role": "user", "content": tool_results},
        ]

    output_text = "".join(b["text"] for b in content if b.get("type") == "text")

    return {"response": output_text, "tool_calls_count": total_tool_calls}
