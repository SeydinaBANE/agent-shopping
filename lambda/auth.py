from __future__ import annotations

import logging
import uuid
from typing import Any

import requests
from jose import jwt
from jose.exceptions import JWTError

GUEST_TENANT = "guest"

_logger = logging.getLogger(__name__)


class AuthError(ValueError):
    pass


def validate_jwt(token: str, jwks_uri: str) -> dict[str, Any]:
    try:
        resp = requests.get(jwks_uri, timeout=5)
        resp.raise_for_status()
        jwks = resp.json()
    except Exception as e:
        raise AuthError(f"Impossible de récupérer la clé publique: {e}") from e

    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise AuthError(f"Token invalide: {e}") from e

    kid = header.get("kid")
    if not kid:
        raise AuthError("Token sans kid")

    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not key:
        raise AuthError("Clé publique introuvable pour ce token")

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except JWTError as e:
        raise AuthError(f"Signature ou expiration invalide: {e}") from e

    return payload


def create_guest_context() -> dict[str, Any]:
    return {
        "sub": f"guest-{uuid.uuid4().hex[:12]}",
        "tenant_id": GUEST_TENANT,
        "user_context": {"client_id": "guest", "mode": "limited"},
    }


def extract_user_context(
    token: str | None,
    jwks_uri: str | None,
) -> dict[str, Any]:
    if not token or not jwks_uri:
        return create_guest_context()

    try:
        payload = validate_jwt(token, jwks_uri)
        return {
            "sub": payload.get("sub", "unknown"),
            "tenant_id": payload.get("tenant_id", GUEST_TENANT),
            "user_context": {
                "client_id": payload.get("user_context", {}).get("client_id", "unknown"),
                "mode": "authenticated",
            },
        }
    except AuthError:
        _logger.warning("auth_fallback_guest", exc_info=True)
        return create_guest_context()
