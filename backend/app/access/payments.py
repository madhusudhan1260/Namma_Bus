"""
Payment service: create an order, verify the payment on the server, refund.

The app never decides that a payment succeeded. It passes the gateway's (order_id, payment_id, signature) to the
backend, which checks the signature with the server-side secret before any ticket is issued.

Providers
- test      Development only (refused when ACCESS_ENV=production). No money moves; every response is labelled.
            The dev-only /payments/test/complete endpoint plays the gateway: it signs a payment with a server-side
            test secret and then goes through exactly the same verification as a real payment.
- razorpay  Razorpay Orders API. Needs RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (server env only). Signature is
            HMAC_SHA256(order_id + "|" + payment_id, key_secret), as documented by Razorpay.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import HTTPException

from .config import settings

TEST_PAYMENT_LABEL = "DEMO PAYMENT — NO REAL MONEY CHARGED"


@dataclass
class Order:
    provider: str
    order_id: str
    amount_paise: int
    currency: str = "INR"
    key_id: Optional[str] = None  # public key id for the checkout widget (never the secret)
    is_test: bool = False


class PaymentProvider:
    name = "base"
    is_test = False

    def create_order(self, amount_paise: int, receipt: str) -> Order:
        raise NotImplementedError

    def verify(self, order_id: str, payment_id: str, signature: str) -> bool:
        raise NotImplementedError

    def refund(self, payment_id: str, amount_paise: int) -> str:
        raise NotImplementedError


def _hmac(secret: str, order_id: str, payment_id: str) -> str:
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


class TestPaymentProvider(PaymentProvider):
    name = "test"
    is_test = True

    @staticmethod
    def _secret() -> str:
        # Derived from a server secret; never sent to the app
        return hashlib.sha256(f"test-payments|{settings.ticket_signing_secret}".encode()).hexdigest()

    def create_order(self, amount_paise: int, receipt: str) -> Order:
        return Order(self.name, f"order_test_{secrets.token_hex(8)}", amount_paise, is_test=True)

    def simulate_gateway(self, order_id: str) -> tuple:
        """What the gateway would hand back after a successful checkout (dev only)."""
        payment_id = f"pay_test_{secrets.token_hex(8)}"
        return payment_id, _hmac(self._secret(), order_id, payment_id)

    def verify(self, order_id: str, payment_id: str, signature: str) -> bool:
        return hmac.compare_digest(_hmac(self._secret(), order_id, payment_id), signature or "")

    def refund(self, payment_id: str, amount_paise: int) -> str:
        return f"rfnd_test_{secrets.token_hex(6)}"


class RazorpayProvider(PaymentProvider):
    name = "razorpay"
    API = "https://api.razorpay.com/v1"

    def _auth(self):
        if not (settings.razorpay_key_id and settings.razorpay_key_secret):
            raise HTTPException(status_code=503, detail="Online payments are not configured yet (Razorpay merchant keys missing).")
        return settings.razorpay_key_id, settings.razorpay_key_secret

    def create_order(self, amount_paise: int, receipt: str) -> Order:
        auth = self._auth()
        try:
            r = httpx.post(f"{self.API}/orders", auth=auth, timeout=10,
                           json={"amount": amount_paise, "currency": "INR", "receipt": receipt[:40], "payment_capture": 1})
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="Payment gateway unavailable. Please try again.")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail="Payment gateway refused the order.")
        return Order(self.name, r.json()["id"], amount_paise, key_id=settings.razorpay_key_id)

    def verify(self, order_id: str, payment_id: str, signature: str) -> bool:
        _, secret = self._auth()
        return hmac.compare_digest(_hmac(secret, order_id, payment_id), signature or "")

    def refund(self, payment_id: str, amount_paise: int) -> str:
        auth = self._auth()
        try:
            r = httpx.post(f"{self.API}/payments/{payment_id}/refund", auth=auth, timeout=10, json={"amount": amount_paise})
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="Refund could not be started; it will need manual follow-up.")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail="Payment gateway refused the refund.")
        return r.json().get("id", "")


_override: Optional[PaymentProvider] = None


def set_payment_provider(provider: Optional[PaymentProvider]) -> None:
    global _override
    _override = provider


def get_payment_provider() -> PaymentProvider:
    if _override is not None:
        return _override
    if settings.payment_provider == "razorpay":
        return RazorpayProvider()
    if settings.payment_provider == "test" and not settings.is_production:
        return TestPaymentProvider()
    raise HTTPException(status_code=503, detail="Online payments are not configured.")
