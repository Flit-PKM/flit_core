"""Cloudflare Turnstile server-side verification for subscribe endpoint."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from config import settings


class TurnstileVerificationError(Exception):
    """Raised when Turnstile token verification fails."""

    pass


async def verify_turnstile_token(
    token: Optional[str],
    client_ip: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Verify a Cloudflare Turnstile token server-side.

    Args:
        token: The cf-turnstile-response token from the client.
        client_ip: Optional client IP for extra validation (use if behind Cloudflare proxy).
        timeout: Request timeout in seconds.

    Returns:
        Dict with verification result from Cloudflare.

    Raises:
        TurnstileVerificationError: If verification fails or request errors occur.
    """
    if not token or not token.strip():
        raise TurnstileVerificationError("Missing Turnstile token")

    if not settings.TURNSTILE_SECRET:
        raise TurnstileVerificationError(
            "TURNSTILE_SECRET environment variable not set"
        )

    payload: Dict[str, str] = {
        "secret": settings.TURNSTILE_SECRET,
        "response": token,
    }
    if client_ip:
        payload["remoteip"] = client_ip

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError as exc:
        raise TurnstileVerificationError(
            f"Verification request failed: {exc}"
        ) from exc

    if not result.get("success"):
        error_codes = result.get("error-codes", ["unknown"])
        raise TurnstileVerificationError(
            f"Turnstile verification failed: {error_codes}"
        )

    return result
