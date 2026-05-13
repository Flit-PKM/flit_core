"""Verify Google ID tokens for Sign-In With Google."""

from __future__ import annotations

from typing import Any

from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


def verify_google_login_id_token(token: str, client_id: str) -> dict[str, Any]:
    """
    Verify a Google ID token and return claims.

    Raises:
        ValueError: Invalid token, wrong audience, missing or unverified email.
    """
    try:
        info = id_token.verify_oauth2_token(
            token, google_requests.Request(), client_id
        )
    except (ValueError, GoogleAuthError) as exc:
        raise ValueError("Invalid Google ID token") from exc

    email = info.get("email")
    if not email or not isinstance(email, str):
        raise ValueError("Token missing email")

    if not info.get("email_verified"):
        raise ValueError("Google email is not verified")

    return info
