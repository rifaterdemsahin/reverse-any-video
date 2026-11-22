"""Stripe, in the stdlib: create a Checkout session, and verify webhook signatures.

Environment (or Key Vault secrets of the same name, upper-case with _ as -):
  STRIPE_SECRET_KEY       sk_test_... while testing, sk_live_... when live
  STRIPE_WEBHOOK_SECRET   whsec_..., the signing secret of the webhook endpoint
Test mode is used as long as the key starts with sk_test_. The module refuses a live key unless
STRIPE_ALLOW_LIVE=1 is set, so a test setup cannot charge real cards by mistake.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import vault

API = "https://api.stripe.com/v1"
TOLERANCE_S = 300


class StripeError(RuntimeError):
    pass


def secret_key() -> str | None:
    return vault.get("STRIPE-SECRET-KEY", "STRIPE_SECRET_KEY") or None


def webhook_secret() -> str | None:
    return vault.get("STRIPE-WEBHOOK-SECRET", "STRIPE_WEBHOOK_SECRET") or None


def configured() -> bool:
    return bool(secret_key())


def check_mode(key: str) -> str:
    if key.startswith("sk_test_"):
        return "test"
    if key.startswith("sk_live_"):
        if os.environ.get("STRIPE_ALLOW_LIVE") == "1":
            return "live"
        raise StripeError("A live Stripe key is set but STRIPE_ALLOW_LIVE is not 1. Using test keys only.")
    raise StripeError("The Stripe key is not a secret key (it should start with sk_test_ or sk_live_).")


def _post(path: str, fields: list[tuple[str, str]], key: str) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{API}{path}", data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise StripeError(f"Stripe HTTP {e.code}: {e.read(200).decode('utf-8', 'replace')}") from None
    except urllib.error.URLError as e:
        raise StripeError(f"Stripe unreachable: {e.reason}") from None


def create_checkout(email: str, pack: str, amount_cents: int, base_url: str, key: str | None = None) -> dict:
    """A Checkout session for one credit pack. The email is the account; metadata carries it back to the webhook."""
    key = key or secret_key()
    if not key:
        raise StripeError("Payments are not set up yet.")
    check_mode(key)
    fields = [
        ("mode", "payment"),
        ("customer_email", email),
        ("success_url", f"{base_url}/account?paid=1"),
        ("cancel_url", f"{base_url}/account?cancelled=1"),
        ("line_items[0][quantity]", "1"),
        ("line_items[0][price_data][currency]", "usd"),
        ("line_items[0][price_data][unit_amount]", str(int(amount_cents))),
        ("line_items[0][price_data][product_data][name]", f"Reverse Any Video credit: {pack}"),
        ("metadata[email]", email),
        ("metadata[pack]", pack),
        ("metadata[credit_cents]", str(int(amount_cents))),
    ]
    session = _post("/checkout/sessions", fields, key)
    return {"id": session.get("id"), "url": session.get("url")}


def verify_signature(payload: bytes, header: str | None, secret: str, now: float | None = None) -> bool:
    """Stripe-Signature: t=<unix>,v1=<hex>. Signed text is '<t>.<payload>'. Rejects old timestamps."""
    if not header or not secret:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, sigs = parts.get("t"), [p.split("=", 1)[1] for p in header.split(",") if p.startswith("v1=")]
    if not ts or not sigs:
        return False
    now = time.time() if now is None else now
    if abs(now - int(ts)) > TOLERANCE_S:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def paid_event(event: dict) -> dict | None:
    """For a completed checkout, the account and the amount to credit. None for any other event."""
    if event.get("type") != "checkout.session.completed":
        return None
    obj = (event.get("data") or {}).get("object") or {}
    if obj.get("payment_status") != "paid":
        return None
    meta = obj.get("metadata") or {}
    try:
        cents = int(meta.get("credit_cents") or 0)
    except ValueError:
        return None
    email = (meta.get("email") or obj.get("customer_email") or "").strip().lower()
    if not email or cents <= 0:
        return None
    return {"email": email, "cents": cents, "ref": obj.get("id") or event.get("id"), "pack": meta.get("pack", "")}
