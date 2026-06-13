from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import patch

import pytest

from rag import (
    _cache_get,
    _cache_set,
    _CACHE_MAX_SIZE,
    _CACHE_TTL_SEC,
    _RAG_CACHE,
    _get_opensearch_client,
    build_rag_context,
    generate_embedding,
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
    mock_client = _mock_client(fake_results)

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
    mock_client = _mock_client([])
    mock_client.indices.exists.return_value = False

    with patch("rag._get_opensearch_client", return_value=mock_client):
        with patch("rag.generate_embedding", return_value=[0.1] * 1024):
            results = search_similar("chaise", "t1")
            assert results == []


def _mock_client(fake_results: list) -> Any:
    class _MockOS:
        class indices:
            @staticmethod
            def exists(index: str) -> bool:
                return True

        def search(self, index: str, body: dict) -> dict:
            hits = [{"_source": r} for r in fake_results]
            return {"hits": {"hits": hits}}

    return _MockOS()


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
