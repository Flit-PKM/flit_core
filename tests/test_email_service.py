"""Tests for email service: send_email via Postmark SMTP."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from service import email


@pytest.mark.asyncio
async def test_send_email_not_configured_returns_false_and_does_not_connect():
    """When email is not configured, send_email returns False without attempting SMTP."""
    mock_settings = MagicMock()
    mock_settings.email_configured = False

    with (
        patch("service.email.settings", mock_settings),
        patch("service.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        result = await email.send_email(
            to="recipient@example.com",
            subject="Test",
            body_text="Body",
        )
        assert result is False
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_configured_calls_aiosmtplib_with_correct_args():
    """When configured, send_email calls aiosmtplib.send with correct host, port, credentials."""
    mock_settings = MagicMock()
    mock_settings.email_configured = True
    mock_settings.POSTMARK_SMTP_TOKEN = "test-token-123"
    mock_settings.POSTMARK_SMTP_FROM_EMAIL = "noreply@example.com"
    mock_settings.POSTMARK_SMTP_FROM_NAME = "Flit"
    mock_settings.POSTMARK_SMTP_HOST = "smtp.postmarkapp.com"
    mock_settings.POSTMARK_SMTP_PORT = 2525

    mock_send = AsyncMock(return_value=None)

    with (
        patch("service.email.settings", mock_settings),
        patch("service.email.aiosmtplib.send", mock_send),
    ):
        result = await email.send_email(
            to="recipient@example.com",
            subject="Test Subject",
            body_text="Plain body",
        )
        assert result is True
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["hostname"] == "smtp.postmarkapp.com"
        assert call_kwargs["port"] == 2525
        assert call_kwargs["username"] == "test-token-123"
        assert call_kwargs["password"] == "test-token-123"
        msg = mock_send.call_args.args[0]
        assert msg["From"] == "Flit <noreply@example.com>"
        assert msg["To"] == "recipient@example.com"
        assert msg["Subject"] == "Test Subject"
        assert msg.get_content().strip() == "Plain body"


@pytest.mark.asyncio
async def test_send_email_includes_html_when_provided():
    """When body_html is provided, message is multipart with plain and HTML alternatives."""
    mock_settings = MagicMock()
    mock_settings.email_configured = True
    mock_settings.POSTMARK_SMTP_TOKEN = "token"
    mock_settings.POSTMARK_SMTP_FROM_EMAIL = "from@example.com"
    mock_settings.POSTMARK_SMTP_FROM_NAME = None
    mock_settings.POSTMARK_SMTP_HOST = "smtp.postmarkapp.com"
    mock_settings.POSTMARK_SMTP_PORT = 2525

    mock_send = AsyncMock(return_value=None)

    with (
        patch("service.email.settings", mock_settings),
        patch("service.email.aiosmtplib.send", mock_send),
    ):
        await email.send_email(
            to="recipient@example.com",
            subject="Subject",
            body_text="Plain",
            body_html="<p>HTML</p>",
        )
        msg = mock_send.call_args.args[0]
        assert msg.is_multipart()
        # Plain text part
        plain_body = msg.get_body(preferencelist=("plain",))
        assert plain_body is not None
        assert plain_body.get_content().strip() == "Plain"
        # HTML alternative was added
        html_body = msg.get_body(preferencelist=("html",))
        assert html_body is not None
        assert "<p>HTML</p>" in html_body.get_content()


@pytest.mark.asyncio
async def test_send_email_multiple_recipients():
    """send_email accepts list of recipients."""
    mock_settings = MagicMock()
    mock_settings.email_configured = True
    mock_settings.POSTMARK_SMTP_TOKEN = "token"
    mock_settings.POSTMARK_SMTP_FROM_EMAIL = "from@example.com"
    mock_settings.POSTMARK_SMTP_FROM_NAME = None
    mock_settings.POSTMARK_SMTP_HOST = "smtp.postmarkapp.com"
    mock_settings.POSTMARK_SMTP_PORT = 2525

    mock_send = AsyncMock(return_value=None)

    with (
        patch("service.email.settings", mock_settings),
        patch("service.email.aiosmtplib.send", mock_send),
    ):
        await email.send_email(
            to=["a@example.com", "b@example.com"],
            subject="Subject",
            body_text="Body",
        )
        msg = mock_send.call_args.args[0]
        assert msg["To"] == "a@example.com, b@example.com"


@pytest.mark.asyncio
async def test_send_email_empty_recipients_returns_false():
    """When recipients list is empty, send_email returns False without connecting."""
    mock_settings = MagicMock()
    mock_settings.email_configured = True
    mock_settings.POSTMARK_SMTP_TOKEN = "token"
    mock_settings.POSTMARK_SMTP_FROM_EMAIL = "from@example.com"

    with (
        patch("service.email.settings", mock_settings),
        patch("service.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        result = await email.send_email(
            to=[],
            subject="Subject",
            body_text="Body",
        )
        assert result is False
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_no_from_email_returns_false():
    """When FROM_EMAIL is not set and not overridden, send_email returns False."""
    mock_settings = MagicMock()
    mock_settings.email_configured = True
    mock_settings.POSTMARK_SMTP_TOKEN = "token"
    mock_settings.POSTMARK_SMTP_FROM_EMAIL = None  # Not set

    with (
        patch("service.email.settings", mock_settings),
        patch("service.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        result = await email.send_email(
            to="recipient@example.com",
            subject="Subject",
            body_text="Body",
        )
        assert result is False
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_failure_returns_false():
    """When aiosmtplib raises, send_email logs and returns False."""
    mock_settings = MagicMock()
    mock_settings.email_configured = True
    mock_settings.POSTMARK_SMTP_TOKEN = "token"
    mock_settings.POSTMARK_SMTP_FROM_EMAIL = "from@example.com"
    mock_settings.POSTMARK_SMTP_FROM_NAME = None
    mock_settings.POSTMARK_SMTP_HOST = "smtp.postmarkapp.com"
    mock_settings.POSTMARK_SMTP_PORT = 2525

    mock_send = AsyncMock(side_effect=Exception("SMTP error"))

    with (
        patch("service.email.settings", mock_settings),
        patch("service.email.aiosmtplib.send", mock_send),
    ):
        result = await email.send_email(
            to="recipient@example.com",
            subject="Subject",
            body_text="Body",
        )
        assert result is False
