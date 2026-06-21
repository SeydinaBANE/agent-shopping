from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from rag import (
    _cache_get,
    _cache_set,
    _CACHE_MAX_SIZE,
    _CACHE_TTL_SEC,
    _RAG_CACHE,
    _get_opensearch_client,
    build_rag_context,
    bulk_index_products,
    ensure_index,
    generate_embedding,
    index_product,
    search_similar,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _RAG_CACHE.clear()


def test_build_rag_context_empty() -> None:
    assert build_rag_context([]) == ""


def test_build_rag_context_formats_products() -> None:
    products = [
        {
            "nom": "Chaise",
            "prix": 49.99,
            "stock": 10,
            "description": "Confortable",
            "categorie": "Meuble",
        },
    ]
    result = build_rag_context(products)
    assert "Chaise" in result
    assert "49.99" in result
    assert "Confortable" in result
    assert "Meuble" in result
    assert "Stock: 10" in result


def test_build_rag_context_missing_fields() -> None:
    products = [{"nom": "Article"}]
    result = build_rag_context(products)
    assert "Article" in result
    assert "0.00" in result
    assert "Sans nom" not in result  # nom is present


def test_search_similar_no_client_returns_empty() -> None:
    with patch("rag._get_opensearch_client", return_value=None):
        results = search_similar("chaise", "tenant-1")
        assert results == []


def test_search_similar_caches_results() -> None:
    fake_results = [{"nom": "Chaise", "prix": 49.99}]
    mock_client = _make_mock_client(fake_results)

    with patch("rag._get_opensearch_client", return_value=mock_client):
        with patch("rag.generate_embedding", return_value=[0.1] * 1024):
            results1 = search_similar("chaise", "t1")
            assert results1 == fake_results

    with patch("rag._get_opensearch_client") as mock_factory:
        results2 = search_similar("chaise", "t1")
        assert results2 == fake_results
        mock_factory.assert_not_called()


def test_cache_ttl_expires() -> None:
    with patch("rag.time.time", return_value=1000000):
        _cache_set("t1", "chaise", [{"nom": "Chaise"}])
        assert _cache_get("t1", "chaise") is not None

    with patch("rag.time.time", return_value=1000000 + _CACHE_TTL_SEC + 1):
        assert _cache_get("t1", "chaise") is None


def test_cache_evicts_lru() -> None:
    for i in range(_CACHE_MAX_SIZE + 1):
        _cache_set("t1", f"query-{i}", [{"nom": f"Product {i}"}])

    assert _cache_get("t1", "query-0") is None
    assert _cache_get("t1", "query-1") is not None


def test_search_similar_no_index_returns_empty() -> None:
    mock_client = _make_mock_client([])
    mock_client.indices.exists.return_value = False

    with patch("rag._get_opensearch_client", return_value=mock_client):
        with patch("rag.generate_embedding", return_value=[0.1] * 1024):
            results = search_similar("chaise", "t1")
            assert results == []


class _MockOS:
    def __init__(self) -> None:
        self.indices = _MockIndices()
        self.index = MagicMock()
        self.search = MagicMock(return_value={"hits": {"hits": []}})


class _MockIndices:
    def __init__(self) -> None:
        self.exists = MagicMock(return_value=True)
        self.create = MagicMock()


def _make_mock_client(fake_results: list[dict[str, Any]]) -> _MockOS:
    client = _MockOS()
    client.search.return_value = {
        "hits": {"hits": [{"_source": r} for r in fake_results]}
    }
    return client


def test_ensure_index_no_client_returns_false() -> None:
    with patch("rag._get_opensearch_client", return_value=None):
        assert ensure_index("tenant-1") is False


def test_ensure_index_exists_returns_true() -> None:
    client = _MockOS()
    client.indices.exists = MagicMock(return_value=True)

    with patch("rag._get_opensearch_client", return_value=client):
        with patch("rag._index_name", return_value="test-tenant-1"):
            assert ensure_index("tenant-1") is True
            client.indices.exists.assert_called_once_with(index="test-tenant-1")
            client.indices.create.assert_not_called()


def test_ensure_index_creates_index() -> None:
    client = _MockOS()
    client.indices.exists = MagicMock(return_value=False)

    with patch("rag._get_opensearch_client", return_value=client):
        with patch("rag._index_name", return_value="test-tenant-1"):
            assert ensure_index("tenant-1") is True
            client.indices.create.assert_called_once()
            kwargs = client.indices.create.call_args.kwargs
            assert kwargs["index"] == "test-tenant-1"
            body = kwargs["body"]
            assert body["settings"]["index.knn"] is True
            assert body["mappings"]["properties"]["id"]["type"] == "keyword"
            assert body["mappings"]["properties"]["nom"]["analyzer"] == "french"
            assert body["mappings"]["properties"]["embedding"]["type"] == "knn_vector"
            assert body["mappings"]["properties"]["embedding"]["dimension"] == 1024


def test_index_product_no_client_returns_false() -> None:
    with patch("rag._get_opensearch_client", return_value=None):
        assert index_product("tenant-1", {"id": "P1"}) is False


def test_index_product_success() -> None:
    client = _MockOS()
    embedding = [0.5] * 1024
    product = {"id": "P1", "nom": "Chaise", "prix": 49.99}

    with patch("rag._get_opensearch_client", return_value=client):
        with patch("rag._index_name", return_value="test-tenant-1"):
            with patch("rag.generate_embedding", return_value=embedding):
                assert index_product("tenant-1", product) is True
                client.index.assert_called_once()
                args, kwargs = client.index.call_args
                assert kwargs["index"] == "test-tenant-1"
                assert kwargs["id"] == "P1"
                assert kwargs["body"]["embedding"] == embedding


def test_index_product_missing_id_raises_keyerror() -> None:
    with patch("rag._get_opensearch_client", return_value=_MockOS()):
        with patch("rag.generate_embedding", return_value=[0.5] * 1024):
            with pytest.raises(KeyError):
                index_product("tenant-1", {"nom": "Chaise"})


def test_bulk_index_products_no_client_returns_zero() -> None:
    with patch("rag._get_opensearch_client", return_value=None):
        assert bulk_index_products("tenant-1", []) == 0


def test_bulk_index_products_success() -> None:
    products = [
        {"id": "P1", "nom": "Chaise", "prix": 49.99},
        {"id": "P2", "nom": "Table", "prix": 129.99},
    ]
    embedding = [0.5] * 1024

    with patch("rag._get_opensearch_client", return_value=_MockOS()):
        with patch("rag._index_name", return_value="test-tenant-1"):
            with patch("rag.generate_embedding", return_value=embedding):
                with patch("rag.helpers.bulk", return_value=(2, [])) as mock_bulk:
                    result = bulk_index_products("tenant-1", products)
                    assert result == 2
                    mock_bulk.assert_called_once()


def test_bulk_index_products_empty_list() -> None:
    with patch("rag._get_opensearch_client", return_value=_MockOS()):
        with patch("rag.helpers.bulk", return_value=(0, [])) as mock_bulk:
            result = bulk_index_products("tenant-1", [])
            assert result == 0
            mock_bulk.assert_called_once()


def test_generate_embedding_returns_floats() -> None:
    fake_embedding = {"embedding": [0.1, 0.2, 0.3]}
    with patch("rag._bedrock_client") as mock_bedrock:
        mock_bedrock.return_value.invoke_model.return_value = {
            "body": io.BytesIO(json.dumps(fake_embedding).encode())
        }
        result = generate_embedding("chaise ergonomique")
        assert result == [0.1, 0.2, 0.3]
        mock_bedrock.return_value.invoke_model.assert_called_once_with(
            modelId="amazon.titan-embed-text-v2:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": "chaise ergonomique"}),
        )


def test_get_opensearch_client_mock_returns_none() -> None:
    with patch.dict("os.environ", {"MOCK_API": "true"}, clear=True):
        assert _get_opensearch_client() is None


def test_get_opensearch_client_localhost_no_ssl() -> None:
    with patch.dict(
        "os.environ",
        {
            "MOCK_API": "false",
            "OPENSEARCH_HOST": "localhost",
            "OPENSEARCH_PORT": "9200",
        },
        clear=True,
    ):
        with patch("rag.OpenSearch") as mock_os:
            client = _get_opensearch_client()
            assert client is not None
            mock_os.assert_called_once()
            _, kwargs = mock_os.call_args
            assert kwargs["use_ssl"] is False


def test_get_opensearch_client_ssl_for_remote() -> None:
    with patch.dict(
        "os.environ",
        {
            "MOCK_API": "false",
            "OPENSEARCH_HOST": "search.example.com",
            "OPENSEARCH_PORT": "443",
        },
        clear=True,
    ):
        with patch("rag.OpenSearch") as mock_os:
            with patch("rag.boto3.Session") as mock_session:
                session = mock_session.return_value
                session.region_name = "eu-west-1"
                session.get_credentials.return_value = _fake_creds()
                client = _get_opensearch_client()
                assert client is not None
                mock_os.assert_called_once()
                _, kwargs = mock_os.call_args
                assert kwargs["use_ssl"] is True


def _fake_creds() -> object:
    class FakeCreds:
        access_key = "AKIA123"
        secret_key = "secret"
        token = "token123"
        region_name = "eu-west-1"

    return FakeCreds()
