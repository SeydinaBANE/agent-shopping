from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt

from handler import _emit_metric, _get_tenant_config, _is_fast_path, _process_tool_calls


def _int_to_base64url(num: int) -> str:
    num_bytes = num.to_bytes((num.bit_length() + 7) // 8, byteorder="big")
    return base64.urlsafe_b64encode(num_bytes).rstrip(b"=").decode("ascii")


def _generate_test_token(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    pub_numbers = private_key.public_key().public_numbers()
    e_b64 = _int_to_base64url(pub_numbers.e)
    n_b64 = _int_to_base64url(pub_numbers.n)

    canonical = json.dumps(
        {"e": e_b64, "kty": "RSA", "n": n_b64}, separators=(",", ":"), sort_keys=True
    )
    kid = (
        base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest())
        .rstrip(b"=")
        .decode("ascii")
    )

    jwk = {
        "kty": "RSA",
        "n": n_b64,
        "e": e_b64,
        "alg": "RS256",
        "use": "sig",
        "kid": kid,
    }
    token = jwt.encode(payload, pem, algorithm="RS256", headers={"kid": kid})
    return token, jwk


class TestIsFastPath:
    def test_bonjour_is_fast(self) -> None:
        assert _is_fast_path("Bonjour") is True

    def test_merci_is_fast(self) -> None:
        assert _is_fast_path("merci") is True

    def test_complex_query_not_fast(self) -> None:
        assert _is_fast_path("Je cherche une robe rouge") is False

    def test_case_insensitive(self) -> None:
        assert _is_fast_path("BONJOUR") is True

    def test_oui_is_fast(self) -> None:
        assert _is_fast_path("oui") is True


class TestLambdaHandler:
    @patch("handler.create_trace")
    @patch("handler.flush")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_guest_request(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_flush: MagicMock,
        mock_create_trace: MagicMock,
    ) -> None:
        from handler import lambda_handler

        mock_create_trace.return_value = MagicMock()
        mock_ssm.return_value.get_parameters_by_path.return_value = {"Parameters": []}
        mock_bedrock.return_value.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps(
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Bonjour ! Comment puis-je vous aider ?",
                                }
                            ],
                        }
                    )
                )
            )
        }

        event = {
            "body": json.dumps(
                {
                    "message": "Bonjour",
                    "history": [],
                    "tenant_id": "test",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000
        context.response_stream = None

        response = lambda_handler(event, context)
        assert response is not None
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "response" in body

    @patch("handler.create_trace")
    @patch("handler.flush")
    @patch("auth.requests.get")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_authenticated_request(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_requests_get: MagicMock,
        mock_flush: MagicMock,
        mock_create_trace: MagicMock,
    ) -> None:
        from handler import lambda_handler

        mock_create_trace.return_value = MagicMock()

        token, jwk = _generate_test_token(
            {
                "sub": "user-123",
                "tenant_id": "mon-client",
                "user_context": {"client_id": "client-456"},
            }
        )

        mock_ssm.return_value.get_parameters_by_path.return_value = {
            "Parameters": [
                {
                    "Name": "/agent-shopping/tenants/mon-client/config",
                    "Value": json.dumps(
                        {
                            "tenant_id": "mon-client",
                            "public_key_jwks_uri": "https://example.com/jwks",
                            "api_base_url": "",
                        }
                    ),
                }
            ]
        }
        mock_requests_get.return_value = MagicMock(
            ok=True, json=lambda: {"keys": [jwk]}
        )
        mock_bedrock.return_value.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps(
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Je cherche dans le catalogue...",
                                }
                            ],
                        }
                    )
                )
            )
        }

        event = {
            "headers": {"Authorization": f"Bearer {token}"},
            "body": json.dumps(
                {
                    "message": "Je cherche un produit",
                    "history": [],
                    "tenant_id": "mon-client",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000
        context.response_stream = None

        response = lambda_handler(event, context)
        assert response is not None
        assert response["statusCode"] == 200

    @patch("auth.requests.get")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_tenant_mismatch_rejected(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_requests_get: MagicMock,
    ) -> None:
        from handler import lambda_handler

        token, jwk = _generate_test_token(
            {
                "sub": "user-123",
                "tenant_id": "tenant-a",
            }
        )

        mock_ssm.return_value.get_parameters_by_path.return_value = {
            "Parameters": [
                {
                    "Name": "/agent-shopping/tenants/tenant-b/config",
                    "Value": json.dumps(
                        {
                            "tenant_id": "tenant-b",
                            "public_key_jwks_uri": "https://example.com/jwks",
                        }
                    ),
                }
            ]
        }
        mock_requests_get.return_value = MagicMock(
            ok=True, json=lambda: {"keys": [jwk]}
        )

        event = {
            "headers": {"Authorization": f"Bearer {token}"},
            "body": json.dumps(
                {
                    "message": "Bonjour",
                    "history": [],
                    "tenant_id": "tenant-b",
                }
            ),
        }
        context = MagicMock()

        response = lambda_handler(event, context)
        assert response is not None
        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert "Tenant mismatch" in body["error"]

    def test_missing_message(self) -> None:
        from handler import lambda_handler

        event = {"body": json.dumps({})}
        context = MagicMock()

        response = lambda_handler(event, context)
        assert response is not None
        assert response["statusCode"] == 400

    def test_invalid_json(self) -> None:
        from handler import lambda_handler

        event = {"body": "not json"}
        context = MagicMock()

        response = lambda_handler(event, context)
        assert response is not None
        assert response["statusCode"] == 400

    @patch("handler.create_trace")
    @patch("handler.flush")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_guest_mode_no_auth_header(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_flush: MagicMock,
        mock_create_trace: MagicMock,
    ) -> None:
        from handler import lambda_handler

        mock_create_trace.return_value = MagicMock()
        mock_ssm.return_value.get_parameters_by_path.return_value = {"Parameters": []}
        mock_bedrock.return_value.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps(
                        {
                            "content": [{"type": "text", "text": "Bonjour !"}],
                        }
                    )
                )
            )
        }

        event = {
            "body": json.dumps(
                {
                    "message": "Bonjour",
                    "history": [],
                    "tenant_id": "default",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000
        context.response_stream = None

        response = lambda_handler(event, context)
        assert response is not None
        assert response["statusCode"] == 200

    @patch("handler.create_trace")
    @patch("handler.flush")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_multi_turn_tool_calls(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_flush: MagicMock,
        mock_create_trace: MagicMock,
    ) -> None:
        from handler import lambda_handler

        mock_create_trace.return_value = MagicMock()
        mock_ssm.return_value.get_parameters_by_path.return_value = {"Parameters": []}

        bedrock_calls: list = []
        bedrock_responses = iter(
            [
                {
                    "content": [
                        {"type": "text", "text": "Je cherche dans le catalogue..."},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "rechercher_produits",
                            "input": {"query": "ordinateur"},
                        },
                        {
                            "type": "tool_use",
                            "id": "toolu_2",
                            "name": "verifier_stock",
                            "input": {"produit_id": "P100"},
                        },
                    ],
                },
                {
                    "content": [{"type": "text", "text": "Voici les résultats..."}],
                },
            ]
        )

        def invoke_model(**kwargs):
            bedrock_calls.append(kwargs)
            resp = next(bedrock_responses)
            return {"body": MagicMock(read=MagicMock(return_value=json.dumps(resp)))}

        mock_bedrock.return_value.invoke_model.side_effect = invoke_model

        event = {
            "body": json.dumps(
                {
                    "message": "Je cherche un ordinateur",
                    "history": [],
                    "tenant_id": "test",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000
        context.response_stream = None

        response = lambda_handler(event, context)
        assert response is not None
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["tool_calls_count"] == 2
        assert "Voici les résultats" in body["response"]
        assert len(bedrock_calls) == 2

        second_call_body = json.loads(bedrock_calls[1]["body"])
        user_messages = [m for m in second_call_body["messages"] if m["role"] == "user"]
        tool_result_blocks = user_messages[-1]["content"]
        assert any(b["type"] == "tool_result" for b in tool_result_blocks)

    @patch("handler.create_trace")
    @patch("handler.flush")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_max_tool_turns_limited(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_flush: MagicMock,
        mock_create_trace: MagicMock,
    ) -> None:
        from handler import MAX_TOOL_TURNS, lambda_handler

        mock_create_trace.return_value = MagicMock()
        mock_ssm.return_value.get_parameters_by_path.return_value = {"Parameters": []}

        def always_tool(**kwargs):
            return {
                "body": MagicMock(
                    read=MagicMock(
                        return_value=json.dumps(
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "toolu_loop",
                                        "name": "rechercher_produits",
                                        "input": {"query": "test"},
                                    }
                                ],
                            }
                        )
                    )
                )
            }

        mock_bedrock.return_value.invoke_model.side_effect = always_tool

        event = {
            "body": json.dumps(
                {
                    "message": "test",
                    "history": [],
                    "tenant_id": "test",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000
        context.response_stream = None

        response = lambda_handler(event, context)
        assert response is not None
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        total_expected = MAX_TOOL_TURNS * 1
        assert body["tool_calls_count"] == total_expected


class TestStreaming:
    @patch("handler.create_trace")
    @patch("handler.flush")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_streaming_text_response(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_flush: MagicMock,
        mock_create_trace: MagicMock,
    ) -> None:
        from handler import lambda_handler

        mock_create_trace.return_value = MagicMock()
        mock_ssm.return_value.get_parameters_by_path.return_value = {"Parameters": []}

        chunks = [
            {
                "chunk": {
                    "bytes": json.dumps(
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        }
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": "Bonjour"},
                        }
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": " !"},
                        }
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {"type": "content_block_stop", "index": 0}
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
                    ).encode()
                }
            },
            {"chunk": {"bytes": json.dumps({"type": "message_stop"}).encode()}},
        ]
        mock_bedrock.return_value.invoke_model_with_response_stream.return_value = {
            "body": chunks
        }

        response_stream = MagicMock()

        event = {
            "body": json.dumps(
                {
                    "message": "Bonjour",
                    "history": [],
                    "tenant_id": "test",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000
        context.response_stream = response_stream

        result = lambda_handler(event, context)
        assert result is None

        written_data = b"".join(c[0][0] for c in response_stream.write.call_args_list)
        assert b"data: " in written_data
        assert b"Bonjour" in written_data
        assert b'type": "done"' in written_data

    @patch("handler.create_trace")
    @patch("handler.flush")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_streaming_with_tool_use(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_flush: MagicMock,
        mock_create_trace: MagicMock,
    ) -> None:
        from handler import lambda_handler

        mock_create_trace.return_value = MagicMock()

        text = "Je cherche dans le catalogue..."
        chunks = [
            {
                "chunk": {
                    "bytes": json.dumps(
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        }
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": text},
                        }
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {"type": "content_block_stop", "index": 0}
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {
                            "type": "content_block_start",
                            "index": 1,
                            "content_block": {
                                "type": "tool_use",
                                "id": "toolu_1",
                                "name": "rechercher_produits",
                                "input": {"query": "test"},
                            },
                        }
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {"type": "content_block_stop", "index": 1}
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}}
                    ).encode()
                }
            },
            {"chunk": {"bytes": json.dumps({"type": "message_stop"}).encode()}},
        ]

        mock_bedrock.return_value.invoke_model_with_response_stream.return_value = {
            "body": chunks
        }
        mock_bedrock.return_value.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps(
                        {"content": [{"type": "text", "text": "Voici les résultats"}]}
                    )
                )
            ),
        }

        response_stream = MagicMock()

        event = {
            "body": json.dumps(
                {
                    "message": "cherche ordinateur",
                    "history": [],
                    "tenant_id": "test",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000
        context.response_stream = response_stream

        result = lambda_handler(event, context)
        assert result is None

        written_data = b"".join(c[0][0] for c in response_stream.write.call_args_list)
        assert b'type": "text"' in written_data
        assert b'type": "tool_start"' in written_data
        assert b'type": "done"' in written_data

    @patch("handler.create_trace")
    @patch("handler.flush")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_streaming_no_tools_returns_text(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_flush: MagicMock,
        mock_create_trace: MagicMock,
    ) -> None:
        from handler import lambda_handler

        mock_create_trace.return_value = MagicMock()

        final_text = "Voici les résultats"
        chunks = [
            {
                "chunk": {
                    "bytes": json.dumps(
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        }
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": final_text},
                        }
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {"type": "content_block_stop", "index": 0}
                    ).encode()
                }
            },
            {
                "chunk": {
                    "bytes": json.dumps(
                        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
                    ).encode()
                }
            },
            {"chunk": {"bytes": json.dumps({"type": "message_stop"}).encode()}},
        ]
        mock_bedrock.return_value.invoke_model_with_response_stream.return_value = {
            "body": chunks
        }

        response_stream = MagicMock()

        event = {
            "body": json.dumps(
                {
                    "message": "ordinateur",
                    "history": [],
                    "tenant_id": "test",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000
        context.response_stream = response_stream

        result = lambda_handler(event, context)
        assert result is None, f"Expected None, got {result}"

        written_data = b"".join(c[0][0] for c in response_stream.write.call_args_list)
        decoded = written_data.decode()
        assert "Voici les résultats" in decoded, f"decoded={repr(decoded)}"


@patch("handler.boto3")
def test_bedrock_client_factory(mock_boto3: MagicMock) -> None:
    from handler import _bedrock_client

    _bedrock_client()
    mock_boto3.client.assert_called_once_with("bedrock-runtime")


@patch("handler.boto3")
def test_ssm_client_factory(mock_boto3: MagicMock) -> None:
    from handler import _ssm_client

    _ssm_client()
    mock_boto3.client.assert_called_once_with("ssm")


def test_message_too_long() -> None:
    from handler import lambda_handler

    event = {
        "body": json.dumps(
            {
                "message": "a" * 2001,
                "history": [],
                "tenant_id": "test",
            }
        ),
    }
    context = MagicMock()

    response = lambda_handler(event, context)
    assert response is not None
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "trop long" in body["error"]


@patch("handler._ssm_client")
def test_get_tenant_config_param_not_found(mock_ssm_factory: MagicMock) -> None:
    mock_client = MagicMock()
    mock_ssm_factory.return_value = mock_client
    ParameterNotFound = type("ParameterNotFound", (Exception,), {})
    mock_client.exceptions.ParameterNotFound = ParameterNotFound
    mock_client.get_parameters_by_path.side_effect = ParameterNotFound("test")

    result = _get_tenant_config("test-tenant")
    assert result == {}


@patch("handler.create_trace")
@patch("handler.flush")
@patch("handler._ssm_client")
@patch("handler._bedrock_client")
def test_rag_context_building(
    mock_bedrock: MagicMock,
    mock_ssm: MagicMock,
    mock_flush: MagicMock,
    mock_create_trace: MagicMock,
) -> None:
    from handler import lambda_handler

    mock_create_trace.return_value = MagicMock()
    mock_ssm.return_value.get_parameters_by_path.return_value = {"Parameters": []}
    mock_bedrock.return_value.invoke_model.return_value = {
        "body": MagicMock(
            read=MagicMock(
                return_value=json.dumps(
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": "Voici les résultats de recherche",
                            }
                        ],
                    }
                )
            )
        )
    }

    fake_rag_results = [
        {
            "nom": "Chaise",
            "prix": 49.99,
            "stock": 10,
            "description": "Confortable",
            "categorie": "Meuble",
        },
    ]

    event = {
        "body": json.dumps(
            {
                "message": "Je cherche une chaise",
                "history": [],
                "tenant_id": "test",
            }
        ),
    }
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 5000
    context.response_stream = None

    with patch("handler.search_similar", return_value=fake_rag_results):
        response = lambda_handler(event, context)

    assert response is not None
    assert response["statusCode"] == 200


@patch("handler._cw_client")
def test_invoke_bedrock_token_metric(mock_cw: MagicMock) -> None:
    from handler import _invoke_bedrock

    mock_bedrock_client = MagicMock()
    mock_bedrock_client.invoke_model.return_value = {
        "body": MagicMock(
            read=MagicMock(
                return_value=json.dumps(
                    {
                        "content": [{"type": "text", "text": "Bonjour"}],
                        "usage": {"input_tokens": 50, "output_tokens": 30},
                    }
                )
            )
        )
    }

    with patch("handler._bedrock_client", return_value=mock_bedrock_client):
        _invoke_bedrock(
            messages=[{"role": "user", "content": "test"}],
            system_prompt="test",
            tools=[],
            fast=False,
        )

    calls = mock_cw.return_value.put_metric_data.call_args_list
    token_calls = [
        c for c in calls if c.kwargs["MetricData"][0]["MetricName"] == "Tokens"
    ]
    assert len(token_calls) == 1
    assert token_calls[0].kwargs["MetricData"][0]["Value"] == 80


def test_process_tool_calls_adapter_exception() -> None:
    adapter = MagicMock()
    adapter.call.side_effect = ValueError("API failure")

    content = [{"type": "tool_use", "id": "toolu_1", "name": "test", "input": {}}]
    blocks, count = _process_tool_calls(content, adapter)
    assert count == 1
    assert blocks[0]["type"] == "tool_result"
    assert "error" in blocks[0]["content"]


@patch("handler.create_trace")
@patch("handler.flush")
@patch("handler._ssm_client")
@patch("handler._bedrock_client")
def test_streaming_token_metric(
    mock_bedrock: MagicMock,
    mock_ssm: MagicMock,
    mock_flush: MagicMock,
    mock_create_trace: MagicMock,
) -> None:
    from handler import lambda_handler

    mock_create_trace.return_value = MagicMock()
    mock_ssm.return_value.get_parameters_by_path.return_value = {"Parameters": []}

    chunks = [
        {
            "chunk": {
                "bytes": json.dumps(
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    }
                ).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps(
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "Bonjour"},
                    }
                ).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps({"type": "content_block_stop", "index": 0}).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps(
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn"},
                        "usage": {"input_tokens": 50, "output_tokens": 30},
                    }
                ).encode()
            }
        },
        {"chunk": {"bytes": json.dumps({"type": "message_stop"}).encode()}},
    ]
    mock_bedrock.return_value.invoke_model_with_response_stream.return_value = {
        "body": chunks
    }

    response_stream = MagicMock()
    event = {
        "body": json.dumps(
            {
                "message": "Bonjour",
                "history": [],
                "tenant_id": "test",
            }
        ),
    }
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 5000
    context.response_stream = response_stream

    result = lambda_handler(event, context)
    assert result is None

    written_data = b"".join(c[0][0] for c in response_stream.write.call_args_list)
    assert b"Bonjour" in written_data
    assert b'type": "done"' in written_data


@patch("handler.create_trace")
@patch("handler.flush")
@patch("handler._ssm_client")
@patch("handler._bedrock_client")
def test_streaming_follow_up_tools(
    mock_bedrock: MagicMock,
    mock_ssm: MagicMock,
    mock_flush: MagicMock,
    mock_create_trace: MagicMock,
) -> None:
    from handler import lambda_handler

    mock_create_trace.return_value = MagicMock()

    chunks = [
        {
            "chunk": {
                "bytes": json.dumps(
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    }
                ).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps(
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "Recherche..."},
                    }
                ).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps({"type": "content_block_stop", "index": 0}).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps(
                    {
                        "type": "content_block_start",
                        "index": 1,
                        "content_block": {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "rechercher_produits",
                            "input": {"query": "test"},
                        },
                    }
                ).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps({"type": "content_block_stop", "index": 1}).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps(
                    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}}
                ).encode()
            }
        },
        {"chunk": {"bytes": json.dumps({"type": "message_stop"}).encode()}},
    ]

    invoke_calls = []
    invoke_responses = iter(
        [
            {
                "content": [
                    {"type": "text", "text": "Suite..."},
                    {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "verifier_stock",
                        "input": {"produit_id": "P100"},
                    },
                ],
            },
            {
                "content": [{"type": "text", "text": "Voici le résultat final"}],
            },
        ]
    )

    def invoke_model(**kwargs):
        invoke_calls.append(kwargs)
        resp = next(invoke_responses)
        return {"body": MagicMock(read=MagicMock(return_value=json.dumps(resp)))}

    mock_bedrock.return_value.invoke_model_with_response_stream.return_value = {
        "body": chunks
    }
    mock_bedrock.return_value.invoke_model.side_effect = invoke_model

    response_stream = MagicMock()
    event = {
        "body": json.dumps(
            {
                "message": "cherche ordinateur",
                "history": [],
                "tenant_id": "test",
            }
        ),
    }
    context = MagicMock()
    context.get_remaining_time_in_millis.return_value = 5000
    context.response_stream = response_stream

    result = lambda_handler(event, context)
    assert result is None

    written_data = b"".join(c[0][0] for c in response_stream.write.call_args_list)
    assert b"tool_start" in written_data
    assert b'type": "done"' in written_data
    assert len(invoke_calls) == 2


@patch("handler.create_trace")
@patch("handler.flush")
@patch("handler._ssm_client")
@patch("handler._bedrock_client")
def test_streaming_timeout_guard(
    mock_bedrock: MagicMock,
    mock_ssm: MagicMock,
    mock_flush: MagicMock,
    mock_create_trace: MagicMock,
) -> None:
    from handler import lambda_handler

    mock_create_trace.return_value = MagicMock()

    chunks = [
        {
            "chunk": {
                "bytes": json.dumps(
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    }
                ).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps({"type": "content_block_stop", "index": 0}).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps(
                    {
                        "type": "content_block_start",
                        "index": 1,
                        "content_block": {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "rechercher_produits",
                            "input": {"query": "test"},
                        },
                    }
                ).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps({"type": "content_block_stop", "index": 1}).encode()
            }
        },
        {
            "chunk": {
                "bytes": json.dumps(
                    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}}
                ).encode()
            }
        },
        {"chunk": {"bytes": json.dumps({"type": "message_stop"}).encode()}},
    ]

    def always_tool(**kwargs):
        return {
            "body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps(
                        {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_loop",
                                    "name": "rechercher_produits",
                                    "input": {"query": "test"},
                                }
                            ],
                        }
                    )
                )
            )
        }

    mock_bedrock.return_value.invoke_model_with_response_stream.return_value = {
        "body": chunks
    }
    mock_bedrock.return_value.invoke_model.side_effect = always_tool

    response_stream = MagicMock()
    event = {
        "body": json.dumps(
            {
                "message": "test",
                "history": [],
                "tenant_id": "test",
            }
        ),
    }
    context = MagicMock()
    context.get_remaining_time_in_millis.side_effect = [5000, 5000, 2000, 2000, 2000]

    context.response_stream = response_stream

    result = lambda_handler(event, context)
    assert result is None


@patch("handler.create_trace")
@patch("handler.flush")
@patch("handler._ssm_client")
@patch("handler._bedrock_client")
def test_conversation_timeout_guard(
    mock_bedrock: MagicMock,
    mock_ssm: MagicMock,
    mock_flush: MagicMock,
    mock_create_trace: MagicMock,
) -> None:
    from handler import lambda_handler

    mock_create_trace.return_value = MagicMock()
    mock_ssm.return_value.get_parameters_by_path.return_value = {"Parameters": []}

    def always_tool(**kwargs):
        return {
            "body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps(
                        {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_loop",
                                    "name": "rechercher_produits",
                                    "input": {"query": "test"},
                                }
                            ],
                        }
                    )
                )
            )
        }

    mock_bedrock.return_value.invoke_model.side_effect = always_tool

    event = {
        "body": json.dumps(
            {
                "message": "test",
                "history": [],
                "tenant_id": "test",
            }
        ),
    }
    context = MagicMock()
    context.get_remaining_time_in_millis.side_effect = [5000, 5000, 2000, 2000, 2000]
    context.response_stream = None

    response = lambda_handler(event, context)
    assert response is not None
    assert response["statusCode"] == 200


class TestMetrics:
    def test_emit_metric_success(self):
        metric_name = "TestMetric"
        value = 42.0
        unit = "Count"
        dims = [{"Name": "Model", "Value": "test-model"}]

        with patch("handler._cw_client") as mock_cw:
            mock_client = MagicMock()
            mock_cw.return_value = mock_client

            _emit_metric(metric_name, value, unit, dims)

            mock_client.put_metric_data.assert_called_once_with(
                Namespace="AgentShopping",
                MetricData=[
                    {
                        "MetricName": metric_name,
                        "Value": value,
                        "Unit": unit,
                        "Dimensions": dims,
                    }
                ],
            )

    def test_emit_metric_failure_logs_warning(self):
        with patch("handler._cw_client") as mock_cw:
            mock_cw.side_effect = Exception("aws down")

            with patch("handler.logger.exception") as mock_exc:
                _emit_metric("FailMetric", 1.0, "Count", [])
                mock_exc.assert_called_once()
                assert mock_exc.call_args[0][0] == "metric_emit_failed"
