"""
One-time sign-in code delivery.

OtpDelivery
  ├── EmailOtpDelivery  OTP_PROVIDER=email — sends the code by email over SMTP (any provider:
  │                     Gmail/Google Workspace, Outlook, Zoho, Amazon SES, Brevo, SendGrid, …).
  ├── MockOtpDelivery   OTP_PROVIDER=mock (development only) — nothing is sent; the code is returned to
  │                     the caller and labelled "DEVELOPMENT CODE — NOT SENT BY EMAIL".
  └── UnavailableOtpDelivery
"""

import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from ..config import settings

logger = logging.getLogger("namma.access.otp")

DEV_NOTICE = "DEVELOPMENT CODE — NOT SENT BY EMAIL"


class OtpDeliveryError(Exception):
    pass


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    shown = name[:1] if len(name) <= 3 else name[:2]
    return f"{shown}{'*' * max(3, len(name) - len(shown))}@{domain}"


class OtpDelivery(ABC):
    is_development = False

    @abstractmethod
    def send(self, email: str, code: str, name: str = "", minutes: int = 10) -> Optional[str]:
        """Deliver the code. Returns the code only for development delivery."""


class MockOtpDelivery(OtpDelivery):
    is_development = True

    def send(self, email: str, code: str, name: str = "", minutes: int = 10) -> Optional[str]:
        logger.info("DEVELOPMENT sign-in code generated (not emailed) for %s", mask_email(email) if email else "unknown")
        return code


class UnavailableOtpDelivery(OtpDelivery):
    def send(self, email: str, code: str, name: str = "", minutes: int = 10) -> Optional[str]:
        raise OtpDeliveryError("Email delivery is not configured")


def build_code_email(to: str, code: str, name: str, minutes: int) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your ನಮ್ಮ Bus sign-in code"
    msg["From"] = formataddr(("ನಮ್ಮ Bus", settings.smtp_from))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=(settings.smtp_from.split("@")[-1] or "namma-bus.local"))
    greeting = f"Hello {name}," if name else "Hello,"
    text = (
        f"{greeting}\n\n"
        f"Your ನಮ್ಮ Bus sign-in code is: {code}\n\n"
        f"It expires in {minutes} minutes and can be used only once.\n"
        "Never share this code. ನಮ್ಮ Bus staff will never ask for it.\n"
        "If you did not try to sign in, change your password.\n\n"
        f"ನಿಮ್ಮ ನಮ್ಮ Bus ಸೈನ್ ಇನ್ ಕೋಡ್: {code}\n"
        f"ಇದು {minutes} ನಿಮಿಷಗಳಲ್ಲಿ ಅವಧಿ ಮುಗಿಯುತ್ತದೆ ಮತ್ತು ಒಮ್ಮೆ ಮಾತ್ರ ಬಳಸಬಹುದು. ಈ ಕೋಡ್ ಅನ್ನು ಯಾರೊಂದಿಗೂ ಹಂಚಿಕೊಳ್ಳಬೇಡಿ.\n"
    )
    msg.set_content(text)
    msg.add_alternative(
        f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#1f2937">
<h2 style="color:#0b2545">🚌 ನಮ್ಮ Bus</h2>
<p>{greeting}</p>
<p>Your sign-in code is</p>
<p style="font-size:32px;font-weight:bold;letter-spacing:6px;color:#0b2545">{code}</p>
<p>It expires in {minutes} minutes and can be used only once.<br>
Never share this code. ನಮ್ಮ Bus staff will never ask for it.<br>
If you did not try to sign in, change your password.</p>
<hr><p>ನಿಮ್ಮ ಸೈನ್ ಇನ್ ಕೋಡ್ <b>{code}</b> — {minutes} ನಿಮಿಷಗಳಲ್ಲಿ ಅವಧಿ ಮುಗಿಯುತ್ತದೆ. ಯಾರೊಂದಿಗೂ ಹಂಚಿಕೊಳ್ಳಬೇಡಿ.</p>
</div>""",
        subtype="html",
    )
    return msg


class EmailOtpDelivery(OtpDelivery):
    def configured(self) -> bool:
        return bool(settings.smtp_host and settings.smtp_from)

    def send(self, email: str, code: str, name: str = "", minutes: int = 10) -> Optional[str]:
        if not self.configured():
            raise OtpDeliveryError("SMTP is not configured (SMTP_HOST / SMTP_FROM)")
        if not email:
            raise OtpDeliveryError("The account has no email address")
        msg = build_code_email(email, code, name, minutes)
        try:
            if settings.smtp_security == "ssl":
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            with server:
                if settings.smtp_security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            # Never log the code or credentials
            logger.warning("Sign-in code email to %s failed: %s", mask_email(email), type(exc).__name__)
            raise OtpDeliveryError("Email could not be sent") from exc
        logger.info("Sign-in code emailed to %s", mask_email(email))
        return None


_override: Optional[OtpDelivery] = None


def get_otp_delivery() -> OtpDelivery:
    if _override is not None:
        return _override
    kind = settings.otp_provider
    if kind in ("email", "smtp"):
        return EmailOtpDelivery()
    if kind == "mock":
        return MockOtpDelivery()
    return UnavailableOtpDelivery()


def set_otp_delivery(delivery: Optional[OtpDelivery]) -> None:
    """Test/integration hook."""
    global _override
    _override = delivery
