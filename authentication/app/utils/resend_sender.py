"""Send emails via Resend (OTP, verification). API key from config only; never in code."""
from __future__ import annotations

import logging
from typing import Optional

from ..core.config import settings

logger = logging.getLogger(__name__)


def send_email(
    to: str,
    subject: str,
    html: str,
    from_email: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Send an email via Resend.
    Returns (success, error_message). error_message is None on success.
    """
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not set; skipping send")
        return False, "Email not configured"
    try:
        import resend
        resend.api_key = settings.resend_api_key
        from_addr = from_email or settings.resend_from_email
        r = resend.Emails.send({
            "from": from_addr,
            "to": to,
            "subject": subject,
            "html": html,
        })
        if getattr(r, "id", None) or r is None:
            return True, None
        return False, str(r)
    except Exception as e:
        logger.exception("Resend send failed")
        return False, str(e)


def build_otp_email_html(code: str, expiry_minutes: int = 15) -> str:
    """Build HTML body for OTP / verification code email."""
    return f"""
    <p>Your verification code is: <strong>{code}</strong></p>
    <p>This code expires in {expiry_minutes} minutes. Do not share it with anyone.</p>
    <p>If you did not request this code, you can ignore this email.</p>
    """
