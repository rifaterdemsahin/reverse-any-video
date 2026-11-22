"""Customer accounts: sign-in by emailed link, a credit balance in cents, and a ledger.

Storage: the Azure container (storage.ProjectStore) under accounts/ and login/. Every purchase is credited once,
identified by its Stripe reference, so a repeated webhook does not add credit twice.

Sessions are a signed cookie: base64url("email|expiry|hmac"). The signing key is SESSION_SECRET (env) or the
Key Vault secret SESSION-SECRET. Without it, sign-in is off.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

import vault

SESSION_TTL = 30 * 24 * 3600
LOGIN_TTL = 15 * 60
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(Exception):
    pass


def normalise(email: str) -> str:
    e = (email or "").strip().lower()
    if len(e) > 254 or not EMAIL_RE.match(e):
        raise AccountError("Enter a valid email address.")
    return e


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _secret() -> bytes:
    s = os.environ.get("SESSION_SECRET") or vault.get("SESSION-SECRET", "SESSION_SECRET")
    if not s:
        raise AccountError("Accounts are not set up on this server (SESSION_SECRET is missing).")
    return s.encode()


class Accounts:
    """`store` is a storage.ProjectStore (or anything with get_json and put_json)."""

    def __init__(self, store):
        self.store = store

    # ----- ledger -----

    def get(self, email: str) -> dict:
        acc = self.store.get_json(f"accounts/{_hash(email)}.json")
        return acc or {"email": email, "balance_cents": 0, "ledger": [], "refs": []}

    def credit(self, email: str, cents: int, ref: str, note: str = "") -> dict:
        """Add credit once. A second call with the same ref changes nothing."""
        if cents <= 0:
            raise AccountError("Credit must be more than zero.")
        acc = self.get(email)
        if ref in acc["refs"]:
            return acc
        acc["balance_cents"] += int(cents)
        acc["refs"].append(ref)
        acc["ledger"].append({"at": int(time.time()), "kind": "credit", "cents": int(cents), "ref": ref, "note": note})
        self.store.put_json(f"accounts/{_hash(email)}.json", acc)
        return acc

    def debit(self, email: str, cents: int, ref: str, note: str = "") -> dict:
        acc = self.get(email)
        if cents <= 0:
            raise AccountError("Debit must be more than zero.")
        if acc["balance_cents"] < cents:
            raise AccountError("Not enough credit. Add credit to continue.")
        acc["balance_cents"] -= int(cents)
        acc["ledger"].append({"at": int(time.time()), "kind": "debit", "cents": int(cents), "ref": ref, "note": note})
        self.store.put_json(f"accounts/{_hash(email)}.json", acc)
        return acc

    # ----- sign-in by emailed link -----

    def start_login(self, email: str) -> str:
        """Returns the one-time token to put in the emailed link. Only its hash is stored."""
        token = secrets.token_urlsafe(32)
        self.store.put_json(f"login/{_hash(token)}.json", {"email": email, "exp": int(time.time()) + LOGIN_TTL})
        return token

    def finish_login(self, token: str) -> str:
        if not token:
            raise AccountError("This sign-in link is not valid.")
        name = f"login/{_hash(token)}.json"
        rec = self.store.get_json(name)
        if not rec or rec.get("exp", 0) < time.time() or rec.get("used"):
            raise AccountError("This sign-in link has expired or was already used. Ask for a new one.")
        rec["used"] = True                      # one use only
        self.store.put_json(name, rec)
        return rec["email"]

    # ----- session cookie -----

    def session_value(self, email: str) -> str:
        payload = f"{email}|{int(time.time()) + SESSION_TTL}"
        sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()

    def email_from_session(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            raw = base64.urlsafe_b64decode(value.encode()).decode()
            email, exp, sig = raw.rsplit("|", 2)
            payload = f"{email}|{exp}"
            good = hmac.compare_digest(hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest(), sig)
            if good and int(exp) > time.time():
                return email
        except (ValueError, UnicodeDecodeError, AccountError):
            return None
        return None
