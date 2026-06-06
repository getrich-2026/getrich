"""JWT helpers using only stdlib (hmac + hashlib + base64).

Token format: <base64url(header)>.<base64url(payload)>.<base64url(signature)>

No external dependencies — pure stdlib.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


_HEADER = {"alg": "HS256", "typ": "JWT"}


def _b64url_encode(data: bytes) -> str:
    """Base64url-encode bytes, stripping padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64url-decode a string, restoring padding."""
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s)


def create_token(
    payload: dict[str, Any],
    secret: str,
    *,
    expires_in: int = 3600,
) -> str:
    """Create a signed JWT.

    Args:
        payload: Claims to include (sub, email, etc.).
        secret: HMAC-SHA256 signing secret.
        expires_in: Token lifetime in seconds (default 1h).

    Returns:
        JWT string: header.payload.signature
    """
    header_b64 = _b64url_encode(json.dumps(_HEADER, separators=(",", ":")).encode())

    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + expires_in}
    body_b64 = _b64url_encode(json.dumps(body, separators=(",", ":")).encode())

    signing_input = f"{header_b64}.{body_b64}"
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{header_b64}.{body_b64}.{sig_b64}"


def verify_token(token: str, secret: str) -> dict[str, Any]:
    """Verify a JWT signature and expiration. Returns the decoded payload.

    Raises:
        ValueError: Invalid token format, bad signature, or expired.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid token format")

    header_b64, body_b64, sig_b64 = parts

    # Validate signature
    signing_input = f"{header_b64}.{body_b64}"
    expected_sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("invalid token signature")

    # Decode payload
    payload: dict[str, Any] = json.loads(_b64url_decode(body_b64))

    # Check expiry
    exp = payload.get("exp", 0)
    if exp < time.time():
        raise ValueError("token expired")

    return payload
