"""Send the finished analysis by email through the Gmail API, using OAuth credentials from Key Vault.

Secrets (vault.py): GMAIL-OAUTH-CLIENT-ID, GMAIL-OAUTH-CLIENT-SECRET, GMAIL-OAUTH-REFRESH-TOKEN.
The sender is the account the refresh token belongs to (info@pexabo.com). Env fallbacks: GMAIL_CLIENT_ID,
GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

import vault

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
MAX_BYTES = 20 * 1024 * 1024   # Gmail accepts 25 MB including encoding overhead


class EmailError(RuntimeError):
    pass


def configured() -> bool:
    return all(vault.get(n, e) for n, e in (("GMAIL-OAUTH-CLIENT-ID", "GMAIL_CLIENT_ID"),
                                            ("GMAIL-OAUTH-CLIENT-SECRET", "GMAIL_CLIENT_SECRET"),
                                            ("GMAIL-OAUTH-REFRESH-TOKEN", "GMAIL_REFRESH_TOKEN")))


def _post(url: str, data: bytes, headers: dict) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise EmailError(f"Gmail HTTP {e.code}: {e.read(200).decode('utf-8', 'replace')}") from None
    except urllib.error.URLError as e:
        raise EmailError(f"Gmail unreachable: {e.reason}") from None


def access_token() -> str:
    body = urllib.parse.urlencode({
        "client_id": vault.get("GMAIL-OAUTH-CLIENT-ID", "GMAIL_CLIENT_ID") or "",
        "client_secret": vault.get("GMAIL-OAUTH-CLIENT-SECRET", "GMAIL_CLIENT_SECRET") or "",
        "refresh_token": vault.get("GMAIL-OAUTH-REFRESH-TOKEN", "GMAIL_REFRESH_TOKEN") or "",
        "grant_type": "refresh_token",
    }).encode()
    token = _post(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"}).get("access_token")
    if not token:
        raise EmailError("Google did not return an access token. Check the Gmail OAuth secrets.")
    return token


def sender_address() -> str:
    """The account the refresh token sends as. Used to confirm the configuration, not to send."""
    req = urllib.request.Request(PROFILE_URL, headers={"Authorization": f"Bearer {access_token()}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["emailAddress"]


def build_message(to: str, subject: str, body: str, sender: str,
                  attachments: list[tuple[str, bytes, str]]) -> EmailMessage:
    msg = EmailMessage()
    msg["To"], msg["From"], msg["Subject"] = to, sender, subject
    msg.set_content(body)
    for name, data, mime in attachments:
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    if len(msg.as_bytes()) > MAX_BYTES:
        raise EmailError("The result is too large to email. Ask for a download link instead.")
    return msg


def send(to: str, subject: str, body: str, attachments: list[tuple[str, bytes, str]] | None = None,
         sender: str | None = None) -> str:
    """Send one message. Returns the Gmail message id."""
    sender = sender or sender_address()
    msg = build_message(to, subject, body, sender, attachments or [])
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    resp = _post(SEND_URL, json.dumps({"raw": raw}).encode(),
                 {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"})
    return resp.get("id", "")
