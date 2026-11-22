"""Customer pages and the account API: the landing page, the price pages, sign-in and the packs.

Routes are registered on the app in server.py. Shared state and helpers live there too.
"""
import json
import os
import re
import time
from pathlib import Path

from fastapi import Form, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

import accounts
import admin
import gmail
import payments
import pricing
import storage
from server import DOCS, PUBLIC_URL, app, get_store

@app.get("/")
def index():
    return FileResponse(DOCS / "landing.html", media_type="text/html")


@app.get("/start")
def start():
    return FileResponse(DOCS / "start.html", media_type="text/html")


# --------------------------------------------------------------------------- #
# Accounts: sign-in by emailed link, credit balance, buying packs              #
# --------------------------------------------------------------------------- #

SESSION_COOKIE = "rav_session"


def get_accounts() -> accounts.Accounts:
    return accounts.Accounts(get_store())


def current_email(request: Request) -> str | None:
    return get_accounts().email_from_session(request.cookies.get(SESSION_COOKIE))


@app.post("/api/account/login")
def account_login(email: str = Form("")):
    try:
        address = accounts.normalise(email)
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    if not gmail.configured():
        raise HTTPException(503, "Sign-in email is not set up on this server.")
    token = get_accounts().start_login(address)
    link = f"{PUBLIC_URL}/api/account/verify?token={token}"
    body = ("Use this link to sign in to Reverse Any Video. It works once and expires in 15 minutes.\n\n"
            f"{link}\n\nIf you did not ask for this, ignore this email.")
    try:
        gmail.send(address, "Your sign-in link", body)
    except gmail.EmailError as e:
        raise HTTPException(503, f"The sign-in email could not be sent: {e}")
    return {"sent": True, "message": "Check your email for the sign-in link."}


@app.get("/api/account/verify")
def account_verify(token: str = ""):
    try:
        address = get_accounts().finish_login(token)
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    resp = RedirectResponse("/account", status_code=303)
    resp.set_cookie(SESSION_COOKIE, get_accounts().session_value(address), max_age=accounts.SESSION_TTL,
                    httponly=True, secure=True, samesite="lax")
    return resp


@app.get("/api/account")
def account_me(request: Request):
    email = current_email(request)
    if not email:
        raise HTTPException(401, "Sign in first.")
    acc = get_accounts().get(email)
    return {"email": email, "balance_cents": acc["balance_cents"], "ledger": acc["ledger"][-20:]}


@app.post("/api/account/logout")
def account_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.post("/api/account/checkout")
def account_checkout(request: Request, pack: str = Form("")):
    email = current_email(request)
    if not email:
        raise HTTPException(401, "Sign in first.")
    try:
        amount = float(pack)
    except ValueError:
        raise HTTPException(400, "Choose a pack.")
    if amount not in pricing.PACKAGE_AMOUNTS:
        raise HTTPException(400, "Unknown pack.")
    if not payments.configured():
        raise HTTPException(503, "Payments are not set up yet. The packs go live once Stripe is connected.")
    try:
        session = payments.create_checkout(email, pricing.PACKAGE_NAMES[amount], int(round(amount * 100)), PUBLIC_URL)
    except payments.StripeError as e:
        raise HTTPException(503, str(e))
    return {"url": session["url"], "id": session["id"]}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    secret = payments.webhook_secret()
    if not secret:
        raise HTTPException(503, "Webhook is not set up yet.")
    if not payments.verify_signature(payload, request.headers.get("stripe-signature"), secret):
        raise HTTPException(400, "Bad signature.")
    try:
        event = json.loads(payload)
    except ValueError:
        raise HTTPException(400, "Not JSON.")
    paid = payments.paid_event(event)
    if paid:
        get_accounts().credit(paid["email"], paid["cents"], paid["ref"], note=f"pack {paid['pack']}")
    return {"received": True}


@app.get("/account")
def account_page():
    return FileResponse(DOCS / "account.html", media_type="text/html")


@app.get("/settings")
def settings_page():
    return RedirectResponse("/admin/settings", status_code=308)


@app.get("/menu.js")
def menu_js():
    return FileResponse(DOCS / "menu.js", media_type="application/javascript")


@app.get("/landing")
def landing():
    return RedirectResponse("/", status_code=308)


@app.get("/pricing")
def pricing_page():
    return FileResponse(DOCS / "pricing.html", media_type="text/html")


@app.get("/setup")
def setup_guide():
    return RedirectResponse("/admin/setup", status_code=308)





