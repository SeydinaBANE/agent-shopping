from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from typing import Any

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
from requests_aws4auth import AWS4Auth

EMBEDDING_MODEL = os.environ.get("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")
EMBEDDING_DIMENSION = 1024

_RAG_CACHE: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
_CACHE_TTL_SEC = 300
_CACHE_MAX_SIZE = 100


def _bedrock_client():
    return boto3.client("bedrock-runtime")


def generate_embedding(text: str) -> list[float]:
    response = _bedrock_client().invoke_model(
        modelId=EMBEDDING_MODEL,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": text}),
    )
    return json.loads(response["body"].read())["embedding"]


def _get_opensearch_client() -> OpenSearch | None:
    host = os.environ.get("OPENSEARCH_HOST", "localhost")
    port = int(os.environ.get("OPENSEARCH_PORT", "9200"))
    mock_api = os.environ.get("MOCK_API", "true").lower() == "true"

    if mock_api:
        return None

    use_ssl = host != "localhost" and "localhost" not in host

    if use_ssl:
        session = boto3.Session()
        credentials = session.get_credentials()
        if credentials:
            auth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                session.region_name or "eu-west-1",
                "aoss",
                session_token=credentials.token,
            )
            return OpenSearch(
                hosts=[{"host": host, "port": port}],
                http_auth=auth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=10,
            )

    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        use_ssl=False,
        connection_class=RequestsHttpConnection,
        timeout=5,
    )


def _index_name(tenant_id: str) -> str:
    prefix = os.environ.get("OPENSEARCH_INDEX_PREFIX", "agent-shopping")
    return f"{prefix}-{tenant_id}"


def ensure_index(tenant_id: str) -> bool:
    client = _get_opensearch_client()
    if client is None:
        return False

    index = _index_name(tenant_id)

    if client.indices.exists(index=index):
        return True

    body = {
        "settings": {
            "index.knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "nom": {"type": "text", "analyzer": "french"},
                "description": {"type": "text", "analyzer": "french"},
                "prix": {"type": "float"},
                "stock": {"type": "integer"},
                "categorie": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": EMBEDDING_DIMENSION,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                    },
                },
            }
        },
    }

    client.indices.create(index=index, body=body)
    return True


def index_product(tenant_id: str, product: dict[str, Any]) -> bool:
    client = _get_opensearch_client()
    if client is None:
        return False

    product_text = " ".join(
        filter(
            None,
            [
                product.get("nom", ""),
                product.get("description", ""),
                " ".join(product.get("tags", [])),
            ],
        )
    )
    embedding = generate_embedding(product_text)

    doc = {**product, "embedding": embedding}
    client.index(index=_index_name(tenant_id), id=product["id"], body=doc)
    return True


def bulk_index_products(tenant_id: str, products: list[dict[str, Any]]) -> int:
    client = _get_opensearch_client()
    if client is None:
        return 0

    def generate_actions():
        for product in products:
            product_text = " ".join(
                filter(
                    None,
                    [
                        product.get("nom", ""),
                        product.get("description", ""),
                        " ".join(product.get("tags", [])),
                    ],
                )
            )
            embedding = generate_embedding(product_text)
            yield {
                "_index": _index_name(tenant_id),
                "_id": product["id"],
                "_source": {**product, "embedding": embedding},
            }

    success, _ = helpers.bulk(client, generate_actions())
    return success


def _cache_key(tenant_id: str, query: str) -> str:
    return f"{tenant_id}:{query}"


def _cache_get(tenant_id: str, query: str) -> list[dict[str, Any]] | None:
    key = _cache_key(tenant_id, query)
    if key not in _RAG_CACHE:
        return None
    ts, results = _RAG_CACHE[key]
    if time.time() - ts > _CACHE_TTL_SEC:
        del _RAG_CACHE[key]
        return None
    _RAG_CACHE.move_to_end(key)
    return results


def _cache_set(tenant_id: str, query: str, results: list[dict[str, Any]]) -> None:
    key = _cache_key(tenant_id, query)
    _RAG_CACHE[key] = (time.time(), results)
    _RAG_CACHE.move_to_end(key)
    if len(_RAG_CACHE) > _CACHE_MAX_SIZE:
        _RAG_CACHE.popitem(last=False)


def search_similar(query: str, tenant_id: str, size: int = 5) -> list[dict[str, Any]]:
    cached = _cache_get(tenant_id, query)
    if cached is not None:
        return cached

    client = _get_opensearch_client()
    if client is None:
        return []

    query_embedding = generate_embedding(query)

    index = _index_name(tenant_id)
    if not client.indices.exists(index=index):
        return []

    response = client.search(
        index=index,
        body={
            "size": size,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": query_embedding,
                        "k": size,
                    }
                }
            },
            "_source": {"excludes": ["embedding"]},
        },
    )

    results = [hit["_source"] for hit in response["hits"]["hits"]]
    _cache_set(tenant_id, query, results)
    return results


def build_rag_context(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""

    lines = ["Voici les produits pertinents du catalogue :", ""]
    for p in results:
        lines.append(
            f"- **{p.get('nom', 'Sans nom')}** — {p.get('prix', 0):.2f}€ "
            f"| Stock: {p.get('stock', 0)} | {p.get('description', '')} "
            f"| Catégorie: {p.get('categorie', '')}"
        )
    lines.append("")
    return "\n".join(lines)
