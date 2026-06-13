from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt

from handler import _is_fast_path


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
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_guest_request(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
    ) -> None:
        from handler import lambda_handler

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

        response = lambda_handler(event, context)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "response" in body

    @patch("auth.requests.get")
    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_authenticated_request(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
        mock_requests_get: MagicMock,
    ) -> None:
        from handler import lambda_handler

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

        response = lambda_handler(event, context)
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
        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert "Tenant mismatch" in body["error"]

    def test_missing_message(self) -> None:
        from handler import lambda_handler

        event = {"body": json.dumps({})}
        context = MagicMock()

        response = lambda_handler(event, context)
        assert response["statusCode"] == 400

    def test_invalid_json(self) -> None:
        from handler import lambda_handler

        event = {"body": "not json"}
        context = MagicMock()

        response = lambda_handler(event, context)
        assert response["statusCode"] == 400

    @patch("handler._ssm_client")
    @patch("handler._bedrock_client")
    def test_guest_mode_no_auth_header(
        self,
        mock_bedrock: MagicMock,
        mock_ssm: MagicMock,
    ) -> None:
        from handler import lambda_handler

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

        response = lambda_handler(event, context)
        assert response["statusCode"] == 200
