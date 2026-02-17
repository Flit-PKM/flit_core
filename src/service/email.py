"""Email service: send email via Postmark SMTP."""

from __future__ import annotations

from email.message import EmailMessage
from typing import List, Optional, Union

import aiosmtplib

from config import settings
from logging_config import get_logger

logger = get_logger(__name__)


async def send_email(
    to: Union[str, List[str]],
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """
    Send an email via Postmark SMTP.

    When email is not configured (POSTMARK_SMTP_TOKEN unset), logs and returns False.
    On send failure, logs the error and returns False (defensive, no exception propagation).

    Args:
        to: Recipient address(es) - single str or list of str.
        subject: Email subject.
        body_text: Plain text body (required).
        body_html: Optional HTML body. When set, creates multipart/alternative.
        from_email: Override default From address. Must match verified Sender in Postmark.
        from_name: Override default From display name.
        reply_to: Optional Reply-To header.

    Returns:
        True if sent successfully, False otherwise (not configured or send failed).
    """
    if not settings.email_configured:
        logger.info(
            "Email not configured (POSTMARK_SMTP_TOKEN unset); skipping send to %s",
            to if isinstance(to, str) else ", ".join(to),
        )
        return False

    token = settings.POSTMARK_SMTP_TOKEN
    from_addr = from_email or settings.POSTMARK_SMTP_FROM_EMAIL
    if not from_addr:
        logger.error(
            "POSTMARK_SMTP_FROM_EMAIL not set; cannot send email. "
            "Set from_email or POSTMARK_SMTP_FROM_EMAIL."
        )
        return False

    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        logger.warning("send_email called with empty recipients; skipping")
        return False

    display_name = from_name or settings.POSTMARK_SMTP_FROM_NAME or ""
    if display_name:
        from_header = f"{display_name} <{from_addr}>"
    else:
        from_header = from_addr

    msg = EmailMessage()
    msg["From"] = from_header
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.POSTMARK_SMTP_HOST,
            port=settings.POSTMARK_SMTP_PORT,
            username=token,
            password=token,
        )
        logger.info("Email sent successfully to %s", ", ".join(recipients))
        return True
    except Exception as e:
        logger.exception("Failed to send email to %s: %s", ", ".join(recipients), e)
        return False
