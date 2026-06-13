from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt

from auth import AuthError, create_guest_context, extract_user_context, validate_jwt


def _int_to_base64url(num: int) -> str:
    num_bytes = num.to_bytes((num.bit_length() + 7) // 8, byteorder="big")
    return base64.urlsafe_b64encode(num_bytes).rstrip(b"=").decode("ascii")


def _generate_keypair() -> tuple[Any, dict[str, Any]]:
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
    return pem, jwk


class TestValidateJWT:
    def test_valid_token(self) -> None:
        pem, jwk = _generate_keypair()
        token = jwt.encode(
            {"sub": "user-123", "tenant_id": "mon-client"},
            pem,
            algorithm="RS256",
            headers={"kid": jwk["kid"]},
        )

        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(ok=True, json=lambda: {"keys": [jwk]})
            payload = validate_jwt(token, "https://example.com/jwks")

        assert payload["sub"] == "user-123"
        assert payload["tenant_id"] == "mon-client"

    def test_invalid_signature(self) -> None:
        pem_a, jwk_a = _generate_keypair()
        pem_b, _ = _generate_keypair()
        token = jwt.encode(
            {"sub": "user-123"},
            pem_b,
            algorithm="RS256",
            headers={"kid": jwk_a["kid"]},
        )

        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(ok=True, json=lambda: {"keys": [jwk_a]})
            with pytest.raises(AuthError, match="Signature ou expiration invalide"):
                validate_jwt(token, "https://example.com/jwks")

    def test_expired_token(self) -> None:
        pem, jwk = _generate_keypair()
        token = jwt.encode(
            {"sub": "user-123", "exp": 1000000},
            pem,
            algorithm="RS256",
            headers={"kid": jwk["kid"]},
        )

        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(ok=True, json=lambda: {"keys": [jwk]})
            with pytest.raises(AuthError, match="Signature ou expiration invalide"):
                validate_jwt(token, "https://example.com/jwks")

    def test_jwks_fetch_failure(self) -> None:
        pem, jwk = _generate_keypair()
        token = jwt.encode(
            {"sub": "user-123"}, pem, algorithm="RS256", headers={"kid": jwk["kid"]}
        )

        with patch("auth.requests.get") as mock_get:
            mock_get.side_effect = Exception("Network error")
            with pytest.raises(AuthError, match="Impossible de récupérer"):
                validate_jwt(token, "https://example.com/jwks")

    def test_jwks_http_error(self) -> None:
        pem, jwk = _generate_keypair()
        token = jwt.encode(
            {"sub": "user-123"}, pem, algorithm="RS256", headers={"kid": jwk["kid"]}
        )

        with patch("auth.requests.get") as mock_get:
            resp = MagicMock(ok=False, status_code=500)
            resp.raise_for_status.side_effect = Exception("HTTP 500")
            mock_get.return_value = resp
            with pytest.raises(AuthError, match="Impossible de récupérer"):
                validate_jwt(token, "https://example.com/jwks")

    def test_token_without_kid(self) -> None:
        pem, _ = _generate_keypair()
        token = jwt.encode({"sub": "user-123"}, pem, algorithm="RS256")

        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                ok=True, json=lambda: {"keys": [{"kty": "RSA", "kid": "some-kid"}]}
            )
            with pytest.raises(AuthError, match="Token sans kid"):
                validate_jwt(token, "https://example.com/jwks")

    def test_key_not_in_jwks(self) -> None:
        pem, _ = _generate_keypair()
        token = jwt.encode(
            {"sub": "user-123"}, pem, algorithm="RS256", headers={"kid": "unknown-kid"}
        )

        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                ok=True, json=lambda: {"keys": [{"kty": "RSA", "kid": "other-kid"}]}
            )
            with pytest.raises(AuthError, match="Clé publique introuvable"):
                validate_jwt(token, "https://example.com/jwks")

    def test_invalid_token_string(self) -> None:
        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                ok=True, json=lambda: {"keys": [{"kty": "RSA", "kid": "some-kid"}]}
            )
            with pytest.raises(AuthError, match="Token invalide"):
                validate_jwt("not-a-jwt", "https://example.com/jwks")


class TestExtractUserContext:
    def test_guest_mode_no_token(self) -> None:
        ctx = extract_user_context(None, "")
        assert ctx["user_context"]["mode"] == "limited"
        assert ctx["user_context"]["client_id"] == "guest"
        assert ctx["sub"].startswith("guest-")

    def test_guest_mode_empty_token(self) -> None:
        ctx = extract_user_context("", "")
        assert ctx["user_context"]["mode"] == "limited"

    def test_guest_mode_no_jwks_uri(self) -> None:
        ctx = extract_user_context("some-token", "")
        assert ctx["user_context"]["mode"] == "limited"

    def test_authenticated_user(self) -> None:
        pem, jwk = _generate_keypair()
        token = jwt.encode(
            {
                "sub": "user-456",
                "tenant_id": "mon-client",
                "user_context": {"client_id": "client-789", "email_hash": "abc123"},
            },
            pem,
            algorithm="RS256",
            headers={"kid": jwk["kid"]},
        )

        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(ok=True, json=lambda: {"keys": [jwk]})
            ctx = extract_user_context(token, "https://example.com/jwks")

        assert ctx["sub"] == "user-456"
        assert ctx["tenant_id"] == "mon-client"
        assert ctx["user_context"]["client_id"] == "client-789"
        assert ctx["user_context"]["mode"] == "authenticated"

    def test_authenticated_user_no_user_context(self) -> None:
        pem, jwk = _generate_keypair()
        token = jwt.encode(
            {"sub": "user-456", "tenant_id": "mon-client"},
            pem,
            algorithm="RS256",
            headers={"kid": jwk["kid"]},
        )

        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(ok=True, json=lambda: {"keys": [jwk]})
            ctx = extract_user_context(token, "https://example.com/jwks")

        assert ctx["sub"] == "user-456"
        assert ctx["user_context"]["client_id"] == "unknown"
        assert ctx["user_context"]["mode"] == "authenticated"

    def test_fallback_to_guest_on_invalid_token(self) -> None:
        with patch("auth.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                ok=True, json=lambda: {"keys": [{"kty": "RSA", "kid": "other-kid"}]}
            )
            ctx = extract_user_context("bad-token", "https://example.com/jwks")

        assert ctx["user_context"]["mode"] == "limited"


class TestCreateGuestContext:
    def test_guest_context_structure(self) -> None:
        ctx = create_guest_context()
        assert "sub" in ctx
        assert ctx["tenant_id"] == "guest"
        assert ctx["user_context"]["client_id"] == "guest"
        assert ctx["user_context"]["mode"] == "limited"
        assert ctx["sub"].startswith("guest-")

    def test_guest_context_unique(self) -> None:
        ctx1 = create_guest_context()
        ctx2 = create_guest_context()
        assert ctx1["sub"] != ctx2["sub"]
