"""Admin sign-in with the Azure account (Microsoft Entra ID, OpenID Connect).

Only ADMIN_EMAIL (default info@deliverypilot.net) from the AZURE_TENANT_ID tenant can open /admin.
Everything else is refused, including other Microsoft accounts in other tenants.

Setup (once): an app registration in the tenant with the redirect URI
  https://reverse-any-video.fly.dev/admin/callback
Its client id and secret go in Key Vault as reverse-any-video-admin-client-id and
reverse-any-video-admin-client-secret (or ADMIN_CLIENT_ID / ADMIN_CLIENT_SECRET env vars).

The id token is read straight from the token endpoint over TLS with the client secret, so its signature is
not checked again here. The issuer, audience, tenant, nonce, expiry and email are checked.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import accounts
import vault

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "info@deliverypilot.net").strip().lower()
ADMIN_COOKIE = "rav_admin"
SESSION_TTL = 8 * 3600
STATE_TTL = 10 * 60
LOGIN = "https://login.microsoftonline.com"


class AdminError(Exception):
    pass


def tenant() -> str | None:
    return os.environ.get("AZURE_TENANT_ID") or vault.get("AZURE-TENANT-ID", "AZURE_TENANT_ID") or None


def client_id() -> str | None:
    return vault.get("reverse-any-video-admin-client-id", "ADMIN_CLIENT_ID") or None


def client_secret() -> str | None:
    return vault.get("reverse-any-video-admin-client-secret", "ADMIN_CLIENT_SECRET") or None


def configured() -> bool:
    try:
        accounts._secret()
    except accounts.AccountError:
        return False
    return bool(tenant() and client_id() and client_secret())


def _sign(payload: str) -> str:
    return hmac.new(accounts._secret(), payload.encode(), hashlib.sha256).hexdigest()


def _pack(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _unpack(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return base64.urlsafe_b64decode(value.encode()).decode()
    except (ValueError, UnicodeDecodeError):
        return None


# ----- the sign-in round trip -----

def new_state() -> tuple[str, str]:
    """(state, nonce). The state carries the nonce and its own expiry, signed, so no cookie is needed."""
    nonce = secrets.token_urlsafe(16)
    payload = f"{nonce}|{int(time.time()) + STATE_TTL}"
    return _pack(f"{payload}|{_sign(payload)}"), nonce


def check_state(state: str | None) -> str:
    """Returns the nonce if the state is genuine and fresh, else raises AdminError."""
    raw = _unpack(state)
    if not raw:
        raise AdminError("The sign-in link is not valid. Start again.")
    try:
        nonce, exp, sig = raw.rsplit("|", 2)
    except ValueError:
        raise AdminError("The sign-in link is not valid. Start again.")
    if not hmac.compare_digest(_sign(f"{nonce}|{exp}"), sig) or int(exp) < time.time():
        raise AdminError("The sign-in link has expired. Start again.")
    return nonce


def authorize_url(redirect_uri: str, state: str, nonce: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": client_id(), "response_type": "code", "redirect_uri": redirect_uri,
        "response_mode": "query", "scope": "openid email profile", "state": state, "nonce": nonce,
        "prompt": "select_account"})
    return f"{LOGIN}/{tenant()}/oauth2/v2.0/authorize?{query}"


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Trade the code for tokens at Microsoft. Returns the decoded id token claims."""
    body = urllib.parse.urlencode({
        "client_id": client_id(), "client_secret": client_secret(), "grant_type": "authorization_code",
        "code": code, "redirect_uri": redirect_uri, "scope": "openid email profile"}).encode()
    req = urllib.request.Request(f"{LOGIN}/{tenant()}/oauth2/v2.0/token", data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tokens = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise AdminError(f"Microsoft refused the sign-in ({e.code}).") from None
    except urllib.error.URLError as e:
        raise AdminError(f"Microsoft could not be reached: {e.reason}") from None
    if "id_token" not in tokens:
        raise AdminError("Microsoft did not return an identity.")
    return decode_claims(tokens["id_token"])


def decode_claims(jwt: str) -> dict:
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode()))
    except (IndexError, ValueError):
        raise AdminError("The identity could not be read.")


def admin_email(claims: dict, expected_nonce: str, now: float | None = None) -> str:
    """The admin email if the claims are the right tenant, app, nonce and person. Raises AdminError otherwise."""
    now = time.time() if now is None else now
    tid = tenant()
    if claims.get("tid") != tid:
        raise AdminError("This account is not in the admin tenant.")
    if not str(claims.get("iss", "")).startswith(f"{LOGIN}/{tid}/"):
        raise AdminError("The identity provider is not the admin tenant.")
    if claims.get("aud") != client_id():
        raise AdminError("The identity was issued for another app.")
    if claims.get("nonce") != expected_nonce:
        raise AdminError("The sign-in does not match this request. Start again.")
    if float(claims.get("exp", 0)) < now:
        raise AdminError("The identity has expired. Start again.")
    email = str(claims.get("preferred_username") or claims.get("email") or claims.get("upn") or "").strip().lower()
    if email != ADMIN_EMAIL:
        raise AdminError("This account is not allowed in the admin area.")
    return email


# ----- the admin session cookie -----

def session_value(email: str) -> str:
    payload = f"{email}|{int(time.time()) + SESSION_TTL}"
    return _pack(f"{payload}|{_sign(payload)}")


def email_from_session(value: str | None) -> str | None:
    raw = _unpack(value)
    if not raw:
        return None
    try:
        email, exp, sig = raw.rsplit("|", 2)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(f"{email}|{exp}"), sig) or int(exp) < time.time():
        return None
    return email if email == ADMIN_EMAIL else None
